"""Shared route helpers: existence lookups and ownership enforcement."""
import db
import errors

# Map collection name -> store dict for generic existence checks.
_STORES = {
    "practice": db.practices,
    "provider": db.providers,
    "employer": db.employers,
    "member": db.members,
    "membership": db.memberships,
    "employer_seat": db.employer_seats,
    "visit_slot": db.visit_slots,
    "visit": db.visits,
    "care_plan": db.care_plans,
    "referral": db.referrals,
    "message_thread": db.message_threads,
    "invoice": db.invoices,
    "payment": db.payments,
}


def get_or_404(kind, ident):
    store = _STORES[kind]
    if ident not in store:
        raise errors.not_found("%s %s does not exist." % (kind, ident))
    return store[ident]


# ---------------------------------------------------------------------------
# Ownership checks for entity-backed roles (PRD §2.1, §3.14)
# ---------------------------------------------------------------------------

def member_id_of_provider_scope(member):
    """The provider that owns a member (for Provider ownership): assigned_provider_id."""
    return member.get("assigned_provider_id")


def require_member_owns(caller, member_id):
    """Member role: X-User-ID must equal member_id."""
    if caller.role == "Member" and caller.user_id != member_id:
        raise errors.forbidden("Member does not own this resource.")


def require_provider_owns(caller, provider_id):
    """Provider role: X-User-ID must equal provider_id."""
    if caller.role == "Provider" and caller.user_id != provider_id:
        raise errors.forbidden("Provider does not own this resource.")


def require_employer_owns(caller, employer_id):
    """Employer role: X-User-ID must equal employer_id."""
    if caller.role == "Employer" and caller.user_id != employer_id:
        raise errors.forbidden("Employer does not own this resource.")
