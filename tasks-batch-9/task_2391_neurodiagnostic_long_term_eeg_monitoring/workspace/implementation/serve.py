"""Launcher.

`start.sh` is re-executed before every individual test when the harness runs
with `--isolation per-test-server`, so the boot path is kept to a single
interpreter launch: the dependency check happens in the same process that goes
on to serve, rather than in a throwaway `python3 -c "import flask"` probe.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def ensure_dependencies():
    try:
        import flask  # noqa: F401
    except ImportError:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-q", "-r",
            os.path.join(HERE, "requirements.txt"),
        ])


def main():
    ensure_dependencies()
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from app import app
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
