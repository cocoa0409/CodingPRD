"""Process entry point. Imports the single canonical `app` module so route
registration and the served Flask instance share one module identity (running
app.py directly would create a separate `__main__` copy and a second Flask app
with no routes)."""
import os

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
