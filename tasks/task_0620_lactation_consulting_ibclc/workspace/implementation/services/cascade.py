"""No-show suspension cascade (PRD §3.6, SCAFFOLD no_show_suspension calc).

The cascade is an ordered chain of mutations on the Client and its consults:

  step 1: client.no_show_strikes += 1 (and return the no-showed consult's credit
          if it held one)
  step 2: if no_show_strikes >= NO_SHOW_SUSPEND_THRESHOLD (>=3, inclusive) the
          client transitions ACTIVE -> SUSPENDED
  step 3: the SUSPENDED transition auto-cancels every OTHER consult of that client
          still in SCHEDULED status; each auto-cancelled consult that held a
          committed package credit returns it (consumed -= 1, never below 0)

Each mutated full resource (client and every auto-cancelled consult) gets its own
updated_at refresh and version bump.
"""
import db
from .common import touch
from .calculations import NO_SHOW_SUSPEND_THRESHOLD
from .lookups import recompute_credits_remaining


def _return_credit(client):
    """Return one committed package credit, never letting consumed fall below 0."""
    if client["package_credits_consumed"] > 0:
        client["package_credits_consumed"] -= 1
    recompute_credits_remaining(client)


def apply_no_show(consult, client):
    """Mutate the no-showed consult to NO_SHOW and run the suspension cascade on
    the client. The consult's own status/version are handled by the caller's
    transition; here we apply the cascade side effects on the client and other
    consults."""
    # CASCADE step 1: strike increment.
    client["no_show_strikes"] += 1
    # If this no-showed consult had a committed package credit, return it.
    if consult.get("package_credit_redeemed"):
        _return_credit(client)

    # CASCADE step 2: suspension threshold (inclusive boundary at 3).
    if client["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD and \
            client["status"] == "ACTIVE":
        client["status"] = "SUSPENDED"
        # CASCADE step 3: auto-cancel every OTHER SCHEDULED consult of this
        # client; return each committed credit.
        for other in db.consults.values():
            if other["id"] == consult["id"]:
                continue
            if other["client_id"] != client["id"]:
                continue
            if other["status"] != "SCHEDULED":
                continue
            other["status"] = "CANCELLED"
            if other.get("package_credit_redeemed"):
                _return_credit(client)
            touch(other)

    # The client itself is mutated by every branch above (strike count at
    # minimum) -> single version bump for the whole client mutation.
    touch(client)
