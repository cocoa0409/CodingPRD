"""Cross-cutting claims: OCC stale-version on hospital posture writes, and the
fixed logical-clock default."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_admin_headers, make_director_headers, make_microbiologist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_antibiogram_with_row, create_published_antibiogram,
    create_empiric_guideline_payload, create_and_adopt_guideline,
    create_hospital_payload,
    api_client, ApiErrorId, CLOCK_START_ISO,
)


def _setup_two_draft_guidelines():
    """One PUBLISHED antibiogram; two DRAFT guidelines (UTI and CAP) on the
    same drug; returns the version captured BEFORE the first adoption."""
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    director = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr DIR", license_no="L-DIR-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    antibiogram, _ = create_published_antibiogram(hospital, mb, patient, drug)
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(hid, "UTI", drug["id"], antibiogram["id"]),
        make_director_headers(director["id"]),
    )
    g1 = get_success_data(res)
    res = api_client.create_empiric_guideline(
        create_empiric_guideline_payload(hid, "CAP", drug["id"], antibiogram["id"]),
        make_director_headers(director["id"]),
    )
    g2 = get_success_data(res)
    pre = get_success_data(api_client.get_hospital(hid, make_director_headers(director["id"])))
    return hospital, director, g1, g2, pre["version"]


def test_occ_guideline_adopt_stale_version_rejected(api):
    """PRD Section 2.7: "Two write operations change hospital-wide clinical
    posture and therefore carry optimistic concurrency protection: publishing
    an antibiogram and adopting an empiric guideline. Each of these requests
    must include `expected_hospital_version`, a non-optional input carrying the
    `version` of the `Hospital` resource as the client last observed it. If the
    hospital's current `version` has advanced beyond that observed value, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller
    would otherwise be publishing against — or adopting onto — a baseline they
    have not seen. Both operations increment the hospital's `version` by one on
    success."

    Design: Corner/cross_cutting/occ_guideline_adopt_stale_version_rejected
    """
    hospital, director, g1, g2, stale_version = _setup_two_draft_guidelines()
    # First adoption succeeds and bumps Hospital.version.
    validate_success(
        api.adopt_empiric_guideline(
            g1["id"], {"expected_hospital_version": stale_version},
            make_director_headers(director["id"]),
        ), 200,
    )
    # Second adoption with the pre-first-adoption version is now stale.
    res = api.adopt_empiric_guideline(
        g2["id"], {"expected_hospital_version": stale_version},
        make_director_headers(director["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    fetched = validate_success(
        api.get_empiric_guideline(g2["id"], make_director_headers(director["id"])), 200
    )
    assert fetched["status"] == "DRAFT"


def test_occ_antibiogram_publish_stale_version_rejected(api):
    """PRD Section 2.7: "Two write operations change hospital-wide clinical
    posture and therefore carry optimistic concurrency protection: publishing
    an antibiogram and adopting an empiric guideline. Each of these requests
    must include `expected_hospital_version`, a non-optional input carrying the
    `version` of the `Hospital` resource as the client last observed it. If the
    hospital's current `version` has advanced beyond that observed value, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting/occ_antibiogram_publish_stale_version_rejected
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    ab1, _ = create_antibiogram_with_row(hospital, mb, patient, drug)
    set_clock(hid, "2026-09-02T00:00:00Z")
    ab2, _ = create_antibiogram_with_row(
        hospital, mb, patient, drug,
        period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        organism="KLEBSIELLA",
    )
    # Capture the version before the first publish.
    stale = get_success_data(
        api_client.get_hospital(hid, make_microbiologist_headers(mb["id"]))
    )["version"]
    validate_success(
        api.publish_antibiogram(
            ab1["id"], {"expected_hospital_version": stale},
            make_microbiologist_headers(mb["id"]),
        ), 200,
    )
    # The first publish bumped Hospital.version; the stale read is now refused.
    res = api.publish_antibiogram(
        ab2["id"], {"expected_hospital_version": stale},
        make_microbiologist_headers(mb["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    fetched = validate_success(
        api.get_antibiogram(ab2["id"], make_microbiologist_headers(mb["id"])), 200
    )
    assert fetched["status"] == "DRAFT"


def test_clock_default_is_fixed_2026_08_01(api):
    """PRD Section 2.4: "Every hospital runs on its own logical clock, exposed
    as the `current_utc` field on the `Hospital` resource. The clock starts at
    exactly 2026-08-01T00:00:00Z when the hospital is created, never falls back
    to wall-clock time, and advances only through an explicit clock-advance
    capability available to `StewardshipDirector` and `StewardshipAdmin`."

    Design: Corner/cross_cutting/clock_default_is_fixed_2026_08_01
    """
    res = api.create_hospital(
        create_hospital_payload(name="H", nhsn_facility_id="NHSN-CLK"),
        make_admin_headers(),
    )
    created = validate_success(res, 201)
    fetched = validate_success(api.get_hospital(created["id"], make_admin_headers()), 200)
    assert fetched["current_utc"] == CLOCK_START_ISO
