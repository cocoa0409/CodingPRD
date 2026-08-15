"""Farm Credit Operating Loan & Line API — Flask entry point."""
import os

from flask import Flask

from db import STORE
from response import register_error_handlers
from routes import (associations, borrowers, budgets, collateral, covenants,
                    deferrals, draws, insurance, loans, patronage,
                    restructure)

app = Flask(__name__, static_folder=None)

register_error_handlers(app)

for module in (associations, borrowers, loans, budgets, collateral, insurance,
               draws, covenants, restructure, deferrals, patronage):
    app.register_blueprint(module.bp)


# Serialize every request through one store lock so create-with-supersede
# races resolve through the OCC version checks deterministically.
@app.before_request
def _acquire_store_lock():
    STORE.lock.acquire()


@app.teardown_request
def _release_store_lock(exc):
    try:
        STORE.lock.release()
    except RuntimeError:
        pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
