"""Server-process bootstrap injected by the runner into spawned servers.

This directory ships a ``sitecustomize.py`` that neutralizes a macOS reverse-DNS
stall in ``socket.getfqdn`` (see that file for the full rationale). Python
auto-imports a top-level ``sitecustomize`` module at interpreter startup if its
directory is on ``sys.path``; ``inject`` prepends THIS directory to a spawned
server's ``PYTHONPATH`` so the patch loads automatically — no edit to the
server-under-test, and no external/manual PYTHONPATH setup.

This package directory is not itself on the runner's ``sys.path`` (its parent,
the ``prd_bench_local_runner`` src root, is), so the bundled ``sitecustomize``
does NOT load in the runner's own processes — only in the server processes we
explicitly inject it into.
"""
import os

_DIR = os.path.dirname(os.path.abspath(__file__))


def inject(env: dict) -> dict:
    """Return a copy of ``env`` with this bootstrap directory prepended to
    PYTHONPATH, so a server spawned with that env auto-loads the sitecustomize
    getfqdn fast-path. Idempotent: a no-op if the directory is already present."""
    out = dict(env)
    existing = out.get("PYTHONPATH", "")
    parts = existing.split(os.pathsep) if existing else []
    if _DIR not in parts:
        parts.insert(0, _DIR)
    out["PYTHONPATH"] = os.pathsep.join(parts)
    return out
