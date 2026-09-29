"""Authentication, role admission, seat resolution, function gates, action gates."""
from core import bad, store

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLE_COMPLIANCE_ADMIN = "ComplianceAdmin"
ROLE_CHAIR = "DisclosureCommitteeChair"
ROLE_CONTROLLER = "Controller"
ROLE_LEGAL = "LegalCounsel"
ROLE_IR = "InvestorRelations"
ROLE_OFFICER = "CertifyingOfficer"
ROLE_BUSINESS = "BusinessLeader"

ALL_ROLES = [
    ROLE_COMPLIANCE_ADMIN,
    ROLE_CHAIR,
    ROLE_CONTROLLER,
    ROLE_LEGAL,
    ROLE_IR,
    ROLE_OFFICER,
    ROLE_BUSINESS,
]

SEAT_BACKED_ROLES = frozenset(
    [ROLE_CHAIR, ROLE_CONTROLLER, ROLE_LEGAL, ROLE_IR, ROLE_OFFICER, ROLE_BUSINESS]
)

FUNCTIONS = ("FINANCE", "LEGAL", "OPERATIONS", "INVESTOR_RELATIONS")


class Actor(object):
    __slots__ = ("user_id", "role", "member")

    def __init__(self, user_id, role, member):
        self.user_id = user_id
        self.role = role
        self.member = member

    @property
    def member_id(self):
        return self.member["id"] if self.member else None


def _function_gate_ok(role, member):
    if role == ROLE_CONTROLLER:
        return member["function"] == "FINANCE"
    if role == ROLE_LEGAL:
        return member["function"] == "LEGAL"
    if role == ROLE_IR:
        return member["function"] == "INVESTOR_RELATIONS"
    if role == ROLE_OFFICER:
        return member["is_officer"] is True
    if role == ROLE_CHAIR:
        return member["voting"] is True
    if role == ROLE_BUSINESS:
        return True
    return True


def authorize(request, roles):
    """Ladder rules 1-4. `roles` is the endpoint's permitted role list."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or str(user_id).strip() == "" or role is None or str(role).strip() == "":
        bad("ERR_UNAUTHENTICATED", "both %s and %s headers are required" % (HEADER_USER_ID, HEADER_USER_ROLE))
    user_id = str(user_id).strip()
    role = str(role).strip()

    # rule 2 -- role must be a known role and admitted by this endpoint
    if role not in ALL_ROLES or role not in roles:
        bad("ERR_ROLE_NOT_PERMITTED", "role '%s' may not call this endpoint" % role)

    member = None
    endpoint_has_seat_role = any(candidate in SEAT_BACKED_ROLES for candidate in roles)
    if endpoint_has_seat_role and role != ROLE_COMPLIANCE_ADMIN:
        # rule 3 -- the identity header must resolve to a CommitteeMember row
        member = store.get("member", user_id)
        if member is None:
            bad("ERR_ROLE_NOT_PERMITTED", "identity does not resolve to a committee member")
        # rule 4 -- the role's function gate
        if not _function_gate_ok(role, member):
            bad("ERR_MEMBER_FUNCTION_MISMATCH", "acting member does not satisfy the '%s' function gate" % role)
    return Actor(user_id, role, member)


# ---------------------------------------------------------------- action vocabulary

ACTIONS = {
    "charter": ["ADOPT", "SUPERSEDE"],
    "member": ["RECUSE", "REINSTATE", "VACATE"],
    "cycle": ["OPEN_CLOSE", "OPEN_REVIEW", "OPEN_CERTIFICATION", "DECLARE_FILING_READY", "ABANDON"],
    "milestone": ["START", "COMPLETE"],
    "subcert": ["SUBMIT", "WITHDRAW"],
    "document": ["SUBMIT_REVIEW", "REQUEST_CHANGES", "APPROVE"],
    "event": ["ASSESS", "DISCLOSE"],
    "correction": ["ASSESS", "RESCIND"],
}

ACTION_ROLES = {
    ("charter", "ADOPT"): [ROLE_CHAIR],
    ("charter", "SUPERSEDE"): [ROLE_CHAIR],
    ("member", "RECUSE"): [ROLE_CHAIR],
    ("member", "REINSTATE"): [ROLE_CHAIR],
    ("member", "VACATE"): [ROLE_CHAIR],
    ("cycle", "OPEN_CLOSE"): [ROLE_CONTROLLER, ROLE_CHAIR],
    ("cycle", "OPEN_REVIEW"): [ROLE_CONTROLLER, ROLE_CHAIR],
    ("cycle", "OPEN_CERTIFICATION"): [ROLE_CONTROLLER, ROLE_CHAIR],
    ("cycle", "ABANDON"): [ROLE_CONTROLLER, ROLE_CHAIR],
    ("cycle", "DECLARE_FILING_READY"): [ROLE_CHAIR],
    ("milestone", "START"): [ROLE_CONTROLLER],
    ("milestone", "COMPLETE"): [ROLE_CONTROLLER],
    ("subcert", "SUBMIT"): [ROLE_BUSINESS],
    ("subcert", "WITHDRAW"): [ROLE_CHAIR],
    ("document", "SUBMIT_REVIEW"): [ROLE_CONTROLLER, ROLE_LEGAL, ROLE_IR],
    ("document", "REQUEST_CHANGES"): [ROLE_CONTROLLER, ROLE_LEGAL],
    ("document", "APPROVE"): [ROLE_CONTROLLER, ROLE_LEGAL],
    ("event", "ASSESS"): [ROLE_LEGAL],
    ("event", "DISCLOSE"): [ROLE_LEGAL],
    ("correction", "ASSESS"): [ROLE_COMPLIANCE_ADMIN],
    ("correction", "RESCIND"): [ROLE_COMPLIANCE_ADMIN],
}


def gate_action(actor, kind, body):
    """Ladder rule 5. Unknown action values are deferred to rule 8."""
    action = body.get("action")
    if isinstance(action, str) and action in ACTIONS[kind]:
        permitted = ACTION_ROLES[(kind, action)]
        if actor.role not in permitted:
            bad(
                "ERR_ROLE_ACTION_MISMATCH",
                "role '%s' may not perform action '%s'" % (actor.role, action),
            )
    return action


def require_action(kind, body):
    """Ladder rule 8 for the action field itself."""
    action = body.get("action")
    if action is None:
        bad("ERR_INVALID_REQUEST", "field 'action' is required")
    if not isinstance(action, str) or action not in ACTIONS[kind]:
        bad("ERR_INVALID_REQUEST", "unknown action '%s'" % (action,))
    return action
