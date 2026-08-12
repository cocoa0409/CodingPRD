"""Corporate Investigations API — Flask entry point.

Validation priority order (PRD §2.8) is enforced here and in handlers:
  1 auth (before_request) -> 2 idempotency (before_request, POST only) ->
  3 endpoint role authorization (before_request) -> 4 existence -> 5 OCC ->
  6 state legality -> 7 SOD/safety -> 8 constraints -> 9 referential ->
  10 temporal.
"""
import json
import os

from flask import Response, g, request

import db
import errors
import resp
import services as svc
from app_factory import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
