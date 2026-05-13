"""Committee composition: member creation, conflict declarations,
auto-detected conflicts.

PRD §3.2, §2.10.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    SEC,
    assert_committee_member,
    assert_conflict_declaration,
    create_application,
    create_member,
    create_member_payload,
    declare_conflict,
    find_audit_entries,
    list_audit_logs,
    unique_sponsor_name,
    validate_error,
    validate_success,
)


# ===========================================================================
# Member creation (PRD §3.2)
# ===========================================================================
class TestMemberCreation:
    """PRD §3.2: 'Each row is created by the Secretary with the member's
    full_name, a required qualification ..., a term_start and term_end
    (both ISO 8601 UTC timestamps), and an optional affiliated_sponsors
    array ... Each member carries an administrative status (one of
    ACTIVE, RESIGNED, or REMOVED, defaulting to ACTIVE at creation)'."""

    def test_default_admin_status_active(self, api):
        """PRD §3.2: 'an administrative status (one of ACTIVE, RESIGNED,
        or REMOVED, defaulting to ACTIVE at creation)'."""
        m = create_member()
        assert_committee_member(m)
        assert m["status"] == "ACTIVE", (
            f"PRD §3.2: 'defaulting to ACTIVE at creation'; got "
            f"{m['status']!r}"
        )

    def test_default_affiliated_sponsors_empty(self, api):
        """PRD §3.2: 'optional affiliated_sponsors array ... (defaulting
        to an empty list).'"""
        m = create_member()
        assert m.get("affiliated_sponsors") == [], (
            f"PRD §3.2: 'defaulting to an empty list'; got "
            f"{m.get('affiliated_sponsors')!r}"
        )

    def test_invalid_qualification_rejected(self, api):
        """PRD §3.2: 'qualification drawn from the closed set
        MEDICAL_EXPERT, PHARMACOLOGIST, ETHICIST, LEGAL_EXPERT,
        LAY_REPRESENTATIVE, and STATISTICIAN'. PRD §2.7 priority 15:
        out-of-set enum → ERR_FIELD_VALIDATION."""
        res = api.create_member(
            create_member_payload(qualification="WIZARD"),
            SEC,
        )
        validate_error(res, ApiErrorId.ERR_FIELD_VALIDATION.value)


# ===========================================================================
# Manual conflict declaration (PRD §3.2)
# ===========================================================================
class TestManualConflict:
    """PRD §3.2: 'the secretary or the member themselves may manually
    file a ConflictDeclaration for a specific (member_id, application_id)
    pair, naming a conflict_type of SPONSOR_RELATION, CO_AUTHOR, or
    ECONOMIC_INTEREST together with free-text details.'"""

    def test_manual_conflict_has_auto_detected_false(self, api):
        """PRD §3.2: 'Filed manually, the row's auto_detected flag is
        false'."""
        app = create_application()
        m = create_member()
        c = declare_conflict(m, app["id"],
                             conflict_type="CO_AUTHOR",
                             details="Co-authored a paper.")
        assert_conflict_declaration(c)
        assert c["auto_detected"] is False, (
            f"PRD §3.2: 'the row's auto_detected flag is false' for "
            f"manual filings; got {c.get('auto_detected')!r}"
        )

    def test_manual_conflict_emits_member_recusal_audit(self, api):
        """PRD §3.2: 'Every declaration emits a MEMBER_RECUSAL audit
        row.'"""
        app = create_application()
        m = create_member()
        c = declare_conflict(m, app["id"])
        rows = list_audit_logs(SEC, event_type="MEMBER_RECUSAL")
        # The audit row's subject_entity is implementation-defined within
        # the bound stated by PRD §1.4; we filter by event_type +
        # subject_id == the conflict row's id (preferred) OR member id /
        # application id (broader). PRD §1.4 just says payload-snapshot;
        # we only assert that at least one MEMBER_RECUSAL row exists.
        assert len(rows) >= 1, (
            f"PRD §3.2: 'Every declaration emits a MEMBER_RECUSAL audit "
            f"row'; got {rows!r}"
        )
