"""Authentication, role authorisation and ClientRepresentative ownership.

Implements PRD 2.10 rungs 1-4, which run before anything else on every
endpoint:

  1  ERR_MISSING_AUTH_HEADERS  (401)  X-User-ID / X-User-Role absent or empty
  2  ERR_UNKNOWN_ROLE          (401)  role outside the six named roles
  3  ERR_ROLE_NOT_PERMITTED    (403)  role not on the endpoint's list
  4  ERR_PROJECT_ACCESS_DENIED (403)  ClientRepresentative reaching outside its
                                     own project, on the six operations of 2.1

Rung 4 is deliberately ahead of path existence (rung 5), so a client rep that
addresses somebody else's project id gets 403 even when that id resolves to
nothing. The one exception is the batch-addressed pair: when the batch itself
does not exist there is no owning project to compare against, so the request
falls through to ERR_BATCH_ORDER_NOT_FOUND.
"""

import functools
import sys
import traceback

from flask import g, jsonify, request

from common import LOCK, ApiError, envelope_error

ROLES = (
    "ProgramManager",
    "ProductionSupervisor",
    "MicrobiologyAnalyst",
    "QaReviewer",
    "QualifiedPerson",
    "ClientRepresentative",
)

CLIENT_REP = "ClientRepresentative"


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def _authenticate():
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_AUTH_HEADERS",
            401,
            "Both X-User-ID and X-User-Role headers are required.",
        )
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", 401, "X-User-Role names no known role.")
    g.user_id = user_id
    g.role = role


def _authorize(roles):
    if g.role not in roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            403,
            "Role %s may not perform this operation." % g.role,
        )


def _access_denied():
    return ApiError(
        "ERR_PROJECT_ACCESS_DENIED",
        403,
        "A ClientRepresentative may only reach its own client project.",
    )


def _json_body():
    """Best-effort JSON body; a malformed body is treated as absent."""
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if isinstance(body, dict):
        return body
    return {}


def _check_ownership(scope, kwargs):
    """Rung 4. `scope` names how the owning project is resolved."""
    if g.role != CLIENT_REP:
        return
    from store import DB

    if scope == "project_path":
        if kwargs.get("project_id") != g.user_id:
            raise _access_denied()
    elif scope == "project_body":
        body = _json_body()
        if body.get("client_project_id") != g.user_id:
            raise _access_denied()
    elif scope == "batch_path":
        batch = DB.batches.get(kwargs.get("batch_id"))
        if batch is None:
            return  # no owner to compare; rung 5 answers with a 404
        if batch["client_project_id"] != g.user_id:
            raise _access_denied()


def endpoint(roles, crep_scope=None):
    """Wrap a view with rungs 1-4, the global store lock and error rendering."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            try:
                _authenticate()
                _authorize(roles)
                with LOCK:
                    _check_ownership(crep_scope, kwargs)
                    return view(*args, **kwargs)
            except ApiError as err:
                response = jsonify(envelope_error(err.error_id, err.message))
                response.status_code = err.http_status
                return response
            except Exception:  # keep the process alive for the next test
                traceback.print_exc(file=sys.stderr)
                response = jsonify(
                    envelope_error(
                        "ERR_INVALID_REQUEST", "The request could not be processed."
                    )
                )
                response.status_code = 400
                return response

        return wrapper

    return decorator


def acting_user():
    return g.user_id
