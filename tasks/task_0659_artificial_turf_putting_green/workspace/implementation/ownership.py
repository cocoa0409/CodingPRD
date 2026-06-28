"""Customer ownership enforcement (PRD 2.1, 2.9).

When X-User-Role is Customer, X-User-ID is the id of the acting Customer, and a
Customer may act only on a project they own (project.customer_id == X-User-ID).
A Customer targeting a project that is not theirs is rejected with
ERR_NOT_PROJECT_OWNER. OpsAdmin/SalesRep/Scheduler carry opaque ids never
compared to any entity.
"""

from errors import err


def enforce_project_ownership(project, user_id, role):
    """If the caller is a Customer, require that they own the project."""
    if role == "Customer" and project["customer_id"] != user_id:
        raise err("ERR_NOT_PROJECT_OWNER", "Customer does not own this project.")
