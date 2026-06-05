"""Auto-loaded by the Python interpreter at startup whenever this directory is
on sys.path. The runner injects this directory into every spawned server
process's PYTHONPATH (see prd_bench_local_runner._dnsboot.inject), so the patch
below applies to the server-under-test without modifying its source.

Why: on some hosts (notably macOS) socket.getfqdn("0.0.0.0") blocks ~5s on a
reverse-DNS (PTR) lookup that times out, because the unspecified address has no
hostname. Werkzeug's dev server calls getfqdn(host) during server_bind purely
to compose its "Running on http://..." startup log line. Under per-test-server
isolation the server is restarted before every test, so that 5s stall is paid
hundreds of times and, under the concurrent stability sweep, can push a boot
past the restart-poll window and surface as a spurious "could not be restarted".

What this changes: only the cosmetic startup log-line hostname, and only for the
unspecified-address cases. The server still binds 0.0.0.0 and serves identical
responses; getfqdn's result is never used for anything but that log line. Named
addresses fall through to the real resolver unchanged, so no legitimate lookup
is altered. No application or test behavior is affected.
"""
import socket as _socket

_real_getfqdn = _socket.getfqdn
_UNSPECIFIED = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn
