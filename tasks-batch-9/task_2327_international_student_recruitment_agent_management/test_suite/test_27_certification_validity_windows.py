"""Training validity is a per-module constant, not one shared number.

Three modules recorded on the same day expire on two different dates because
each module carries its own validity length.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE, OFFICER


class TestModuleValidityConstants:
    def test_the_same_issue_date_yields_two_different_expiry_dates(self, client):
        """One year for accuracy and visa integrity, half a year for claims.

        "Validity is derived, not supplied. `expires_on` is `issued_on` advanced by
        the module's validity period: one full year for `PROGRAM_ACCURACY`, half a
        year — 180 days — for `PROHIBITED_CLAIMS`, and one full year for
        `VISA_INTEGRITY`, where a full year is 365 days."

        "A score below 80 is refused with `ERR_TRAINING_SCORE_INSUFFICIENT`"

        Design: Corner/calculations/certification_expires_on_uses_module_validity_constants
        """
        agency = fx.register_agency(
            client, legal_name="Validity Constants Agency", complete_diligence=False
        )

        accuracy = fx.record_certification(
            client, agency["id"], C.MODULE_PROGRAM_ACCURACY, 92, C.DEFAULT_CLOCK_DATE
        )
        claims = fx.record_certification(
            client,
            agency["id"],
            C.MODULE_PROHIBITED_CLAIMS,
            88,
            C.DEFAULT_CLOCK_DATE,
            COMPLIANCE,
        )
        visa = fx.record_certification(
            client, agency["id"], C.MODULE_VISA_INTEGRITY, 80, C.DEFAULT_CLOCK_DATE
        )

        assert accuracy["expires_on"] == "2027-08-01"
        assert accuracy["status"] == C.CERT_VALID

        assert claims["expires_on"] == "2027-01-28"
        assert claims["status"] == C.CERT_VALID

        assert visa["expires_on"] == "2027-08-01"
        assert visa["status"] == C.CERT_VALID, (
            "a score of exactly 80 sits on the accepted side of the floor"
        )

    def test_all_three_modules_coexist_on_one_agency(self, client):
        """The uniqueness rule is per module, so three live records is legal.

        "An agency may hold at most one certification in `VALID` status per module; a
        second live record for the same module is `ERR_DUPLICATE_RESOURCE`."

        "Certifications can be listed for an agency and filtered by `module_code` and
        by `status`."

        Design: Corner/calculations/certification_expires_on_uses_module_validity_constants
        """
        agency = fx.register_agency(
            client, legal_name="Validity Constants Agency", complete_diligence=False
        )
        for module, score in (
            (C.MODULE_PROGRAM_ACCURACY, 92),
            (C.MODULE_PROHIBITED_CLAIMS, 88),
            (C.MODULE_VISA_INTEGRITY, 80),
        ):
            fx.record_certification(
                client, agency["id"], module, score, C.DEFAULT_CLOCK_DATE
            )

        records, meta = validate_paginated(
            client.list_certifications(agency["id"], OFFICER)
        )
        assert meta["total_count"] == 3
        assert {row["module_code"] for row in records} == {
            C.MODULE_PROGRAM_ACCURACY,
            C.MODULE_PROHIBITED_CLAIMS,
            C.MODULE_VISA_INTEGRITY,
        }
