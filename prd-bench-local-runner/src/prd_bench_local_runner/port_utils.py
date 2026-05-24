"""Port management utilities: registry-backed free port allocation, kill processes on a port, URL parsing."""

import contextlib
import errno
import fcntl
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger


def extract_port_from_url(url: str) -> int:
    """Extract port number from a URL. Defaults to 10000 if not specified."""
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return 10000


def is_port_in_use(port: int) -> bool:
    """Check if a port is currently in use via socket connect."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def kill_port(port: int) -> None:
    """
    Kill any process LISTENING on the given TCP port.

    Strictly filtered to the LISTEN-state socket so we never SIGKILL a
    process that merely holds a client-side connection to this port. Without
    the filter, the client end of an HTTP keep-alive connection looks
    identical to the server end in `lsof -i:<port>` output, and a naive
    `xargs kill -9` would take down the client (e.g. the pytest process
    that just made the request) along with the server. This matters for any
    server framework that defaults to HTTP/1.1 keep-alive — Node/Express,
    Go net/http, FastAPI/uvicorn, Spring Boot, etc. — and is invisible for
    frameworks that close connections per-request (Flask/Werkzeug dev
    server), which is why the bug only surfaces for some implementations.

    Best-effort; swallows errors. `fuser -k <port>/tcp` is deliberately not
    used as a fallback because it has no LISTEN-state filter and would
    re-introduce the same bug on Linux systems without lsof.
    """
    # Use a sh idiom (capture-then-test) instead of `xargs -r` so the
    # command behaves the same under GNU xargs (Linux) and BSD xargs (macOS).
    commands = [
        # Primary: lsof with explicit TCP state filter. Works on Linux and macOS.
        f"pids=$(lsof -ti:{port} -sTCP:LISTEN 2>/dev/null); "
        f"[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null; true",
        # Linux fallback: ss -l limits to listening sockets by definition.
        f"pids=$(ss -H -ltnp 'sport = :{port}' 2>/dev/null "
        f"| grep -oE 'pid=[0-9]+' | cut -d= -f2); "
        f"[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null; true",
    ]

    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, timeout=5, capture_output=True)
            if not is_port_in_use(port):
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue


# ---------------------------------------------------------------------------
# File-backed port registry
#
# Concurrent `prd-bench-local-run` instances on the same host coordinate
# through a small TSV file so they never hand out the same port.
#
# File format (one record per line):
#     <port>\t<pid>\t<acquired_at_epoch>
#
# Access is serialised via fcntl.flock on the file itself.
# ---------------------------------------------------------------------------


_DEFAULT_REGISTRY = Path.home() / ".cache" / "prd-bench-local-runner" / "ports.tsv"
_STALE_TTL_SECONDS = 24 * 3600  # entries older than this are treated as dead
_ACQUIRE_MAX_ATTEMPTS = 32      # how many times to retry kernel-asks-for-free if it keeps colliding


def _registry_path() -> Path:
    override = os.environ.get("PRD_BENCH_PORT_REGISTRY")
    return Path(override) if override else _DEFAULT_REGISTRY


def _ensure_registry_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


@contextlib.contextmanager
def _locked_registry() -> Iterator[Path]:
    """Hold an exclusive flock on a sibling .lock file while operating on the registry.

    We flock a separate lock file (not the registry itself) because the
    registry is rewritten via os.replace, which swaps the inode out from
    underneath any fd that opened the old file — once that happens, advisory
    flocks held on the old inode no longer serialise against new readers.
    """
    path = _registry_path()
    _ensure_registry_file(path)
    lock_path = path.with_suffix(path.suffix + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else — still alive.
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def _read_entries(path: Path) -> List[Tuple[int, int, float]]:
    entries: List[Tuple[int, int, float]] = []
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return entries
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            port = int(parts[0])
            pid = int(parts[1])
            acquired_at = float(parts[2])
        except ValueError:
            continue
        entries.append((port, pid, acquired_at))
    return entries


def _write_entries(path: Path, entries: List[Tuple[int, int, float]]) -> None:
    body = "".join(f"{port}\t{pid}\t{acquired_at:.0f}\n" for port, pid, acquired_at in entries)
    # PID-unique tmp filename so concurrent writers (each holding the flock in
    # turn) don't trip over each other's tmp file mid-rename.
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(body)
    os.replace(tmp, path)


def _gc_entries(entries: List[Tuple[int, int, float]]) -> List[Tuple[int, int, float]]:
    """Drop entries whose PID is no longer alive, or that exceed the stale TTL."""
    now = time.time()
    live: List[Tuple[int, int, float]] = []
    dropped: List[Tuple[int, int, str]] = []
    for port, pid, acquired_at in entries:
        if now - acquired_at > _STALE_TTL_SECONDS:
            dropped.append((port, pid, "stale-ttl"))
            continue
        if not _pid_alive(pid):
            dropped.append((port, pid, "dead-pid"))
            continue
        live.append((port, pid, acquired_at))
    if dropped:
        logger.info(
            "port-registry GC swept {n} entries: {detail}",
            n=len(dropped),
            detail=", ".join(f"port={p} pid={pid} reason={why}" for p, pid, why in dropped),
        )
    return live


def _ask_kernel_for_free_port() -> int:
    """Ask the OS for an unused ephemeral port and return it.

    The socket is closed before returning, so the port becomes available for
    the next bind(). The registry guards against another runner picking the
    same port between this call and the server actually binding it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def acquire_port() -> int:
    """Claim a free TCP port and record ownership in the registry.

    Returns the port number. Caller is responsible for eventually calling
    release_port(port) (typically via try/finally and atexit).

    Raises RuntimeError if the registry keeps colliding past the retry budget.
    """
    pid = os.getpid()
    with _locked_registry() as path:
        entries = _gc_entries(_read_entries(path))
        taken = {port for port, _pid, _t in entries}
        for attempt in range(_ACQUIRE_MAX_ATTEMPTS):
            candidate = _ask_kernel_for_free_port()
            if candidate in taken:
                logger.debug(
                    "port-registry candidate {port} already claimed, retrying (attempt {n})",
                    port=candidate, n=attempt + 1,
                )
                continue
            entries.append((candidate, pid, time.time()))
            _write_entries(path, entries)
            logger.info(
                "port-registry acquired port {port} (pid={pid}, registry={path}, holders={n})",
                port=candidate, pid=pid, path=path, n=len(entries),
            )
            return candidate
    raise RuntimeError(
        f"could not acquire a free port after {_ACQUIRE_MAX_ATTEMPTS} attempts "
        f"(registry={path})"
    )


def release_port(port: int) -> None:
    """Remove this process's claim on the given port. Idempotent and best-effort."""
    pid = os.getpid()
    try:
        with _locked_registry() as path:
            entries = _read_entries(path)
            kept = [
                (p, owner, t)
                for (p, owner, t) in entries
                if not (p == port and owner == pid)
            ]
            if len(kept) != len(entries):
                _write_entries(path, kept)
                logger.info(
                    "port-registry released port {port} (pid={pid}, holders={n})",
                    port=port, pid=pid, n=len(kept),
                )
            else:
                logger.debug(
                    "port-registry release port {port} was a no-op (pid={pid} did not hold it)",
                    port=port, pid=pid,
                )
    except OSError as exc:
        logger.warning("port-registry release of port {port} failed: {err}", port=port, err=exc)


def registered_ports() -> List[Tuple[int, int, float]]:
    """Return the current live registry contents (after GC). Mainly for tests/debug."""
    with _locked_registry() as path:
        entries = _gc_entries(_read_entries(path))
        _write_entries(path, entries)
        return entries
