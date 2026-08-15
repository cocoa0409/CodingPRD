"""Validity dossiers, form publication gating, and archival timing."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
)
from test_helpers.factories import create_dossier_payload
from test_helpers.fixtures import (
    ASSEMBLER_H,
    PD_H,
    PSYCH_H,
    build_assembled_form,
    create_dossier,
    create_program,
    create_standard,
    make_operational_items,
    setup_published_form,
)


class TestDossierValidation:
    def test_validation_dossier_content_min_200_chars(self, api):
        """PRD: "A dossier whose body is too short, whose kind is not a valid
        value, or whose form does not exist is rejected with
        `ERR_DOSSIER_INVALID` (HTTP 422)."

        Design: Corner/validations/validation_dossier_content_min_200_chars
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = make_operational_items(program["id"], standard["id"], [30])[0]
        form = build_assembled_form(program["id"], [item])
        resp = api.create_validity_dossier(
            create_dossier_payload(program["id"], form["id"],
                                   content_md="too short"),
            PSYCH_H,
        )
        validate_error(resp, ApiErrorId.ERR_DOSSIER_INVALID)

    def test_dossier_supersede_from_draft_returns_invalid_state(self, api):
        """PRD: "the `Psychometrician` supersedes it — permitted only from
        `PUBLISHED` (`ERR_DOSSIER_NOT_PUBLISHED` otherwise)"

        Design: Corner/state_machines/dossier_supersede_from_draft_returns_invalid_state
        """
        program = create_program()
        standard = create_standard(program["id"])
        item = make_operational_items(program["id"], standard["id"], [30])[0]
        form = build_assembled_form(program["id"], [item])
        dossier = create_dossier(program["id"], form["id"])
        assert dossier["status"] == "DRAFT"
        resp = api.supersede_validity_dossier(dossier["id"], PSYCH_H)
        validate_error(resp, ApiErrorId.ERR_DOSSIER_NOT_PUBLISHED)


class TestPublicationAndArchival:
    def test_error_archive_too_early(self, api):
        """PRD: "After administration, the `ProgramDirector` archives a
        `PUBLISHED` form (`ERR_FORM_NOT_PUBLISHED` otherwise), but only once
        the program clock has advanced strictly more than 90 days past the
        form's `intended_admin_date` (`ERR_ARCHIVE_TOO_EARLY`, HTTP 409)."
        (The clock sits weeks before the intended administration date, far
        inside the 90-day guard. The PUBLISHED form is reached through the
        declared equate + dossier-publish + publish chain.)

        Design: Corner/errors/error_archive_too_early
        """
        program = create_program()
        standard = create_standard(program["id"])
        form = setup_published_form(program["id"], standard["id"],
                                    admin_date="2026-09-01T00:00:00Z")
        assert form["status"] == "PUBLISHED"
        resp = api.archive_test_form(form["id"], PD_H)
        validate_error(resp, ApiErrorId.ERR_ARCHIVE_TOO_EARLY)
        after = get_success_data(api.get_test_form(form["id"], ASSEMBLER_H))
        assert after["status"] == "PUBLISHED", "the rejected archive changes nothing"
