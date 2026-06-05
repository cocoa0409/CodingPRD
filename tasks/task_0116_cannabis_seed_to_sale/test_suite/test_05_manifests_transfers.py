"""Transfer manifests: cyclic depart/recall, cross-entity state preconditions,
single-open-manifest membership, custody-conserving invariants, OCC staleness,
and receive."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_cultivation_license, create_testing_license,
    create_active_package, create_manifest, add_manifest_line,
    create_draft_manifest_with_line, depart_manifest, record_reconciliation_count,
    dist_h, cult_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Rule 3 (non_linear_state_machine): cyclic depart -> recall loop
# ---------------------------------------------------------------------------
def test_depart_moves_manifest_and_package_in_transit(api):
    """PRD §3.6: "On departure the manifest's status becomes `IN_TRANSIT`, its
    `departed_at` is set to the current clock, every line's package is cascaded
    from `ACTIVE` to `IN_TRANSIT` (each package's `version` advancing), and the
    manifest's `version` increments."

    Design: Difficulty/non_linear_state_machine/manifest_cyclic_depart_recall_loop
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    departed = validate_success(depart_manifest(man["id"], expected_version=man["version"]))
    assert departed["status"] == "IN_TRANSIT"
    pkg_after = validate_success(api.get_package(pkg["id"], dist_h()))
    assert pkg_after["status"] == "IN_TRANSIT"


def test_recall_returns_manifest_to_draft_and_package_active(api):
    """PRD §3.6: "A manifest in transit may be recalled back to `DRAFT` by the
    distributor, which clears `departed_at` to null and cascades every line's
    package from `IN_TRANSIT` back to `ACTIVE`, incrementing the manifest's
    `version`"

    Design: Difficulty/non_linear_state_machine/manifest_cyclic_depart_recall_loop
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    validate_success(depart_manifest(man["id"], expected_version=man["version"]))
    recalled = validate_success(api.recall_manifest(man["id"], dist_h()))
    assert recalled["status"] == "DRAFT"
    assert recalled["departed_at"] is None
    pkg_after = validate_success(api.get_package(pkg["id"], dist_h()))
    assert pkg_after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Rule 7 (cross_entity_state_dependency): depart requires package ACTIVE
# ---------------------------------------------------------------------------
def test_depart_with_on_hold_package_rejected(api):
    """PRD §3.6: "Departure is permitted only when the manifest is `DRAFT`, has
    at least one line, every line's package is in `ACTIVE` status with
    `lab_hold` false, the origin license is `ACTIVE`, and the supplied
    `expected_manifest_version` matches the manifest's current `version`"

    Design: Difficulty/cross_entity_state_dependency/manifest_depart_requires_package_active
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    # Place the package ON_HOLD via a discrepant reconciliation count
    # (counted 50 vs remaining 100 => |variance| 50 > 0.5).
    record_reconciliation_count(pkg["id"], counted_grams=50.0,
                                counted_by_user_id="audit-1",
                                counted_at="2026-06-09T00:00:00Z")
    on_hold = validate_success(api.get_package(pkg["id"], dist_h()))
    assert on_hold["status"] == "ON_HOLD"
    man = validate_success(api.get_manifest(man["id"], dist_h()))
    resp = api.depart_manifest(man["id"], {"expected_manifest_version": man["version"]}, dist_h())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_depart_rejection_leaves_manifest_draft(api):
    """PRD §3.6: "A line may be attached only while the manifest is in `DRAFT`"
    PRD §3.6: "Departing a manifest moves it from `DRAFT` to `IN_TRANSIT`."

    Design: Difficulty/cross_entity_state_dependency/manifest_depart_requires_package_active
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    record_reconciliation_count(pkg["id"], counted_grams=50.0,
                                counted_by_user_id="audit-1",
                                counted_at="2026-06-09T00:00:00Z")
    man = validate_success(api.get_manifest(man["id"], dist_h()))
    api.depart_manifest(man["id"], {"expected_manifest_version": man["version"]}, dist_h())
    after = validate_success(api.get_manifest(man["id"], dist_h()))
    assert after["status"] == "DRAFT", "manifest must remain DRAFT after rejected depart"


# ---------------------------------------------------------------------------
# Rule 8 (resource_temporal_overlap): single open-manifest membership
# ---------------------------------------------------------------------------
def test_attach_package_to_second_open_manifest_rejected(api):
    """PRD §3.6: "A package may sit on at most one open manifest line at a time —
    that is, on at most one manifest in `DRAFT` or `IN_TRANSIT` — so attaching a
    package that is already on another open manifest line is rejected as a
    transfer-window overlap with `ERR_MANIFEST_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/package_single_open_manifest_membership
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    man2 = create_manifest(dist["id"], dest["id"])
    resp = api.add_manifest_line(man2["id"], {"package_id": pkg["id"], "grams": 50}, dist_h())
    validate_error(resp, ApiErrorId.ERR_MANIFEST_OVERLAP.value)


def test_package_attachable_to_single_manifest_only(api):
    """PRD §3.6: "A package may sit on at most one open manifest line at a time —
    that is, on at most one manifest in `DRAFT` or `IN_TRANSIT` — so attaching a
    package that is already on another open manifest line is rejected as a
    transfer-window overlap with `ERR_MANIFEST_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/package_single_open_manifest_membership
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man1 = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    # First manifest legitimately holds the package.
    assert man1["line_count"] == 1
    man2 = create_manifest(dist["id"], dest["id"])
    resp = api.add_manifest_line(man2["id"], {"package_id": pkg["id"], "grams": 25}, dist_h())
    validate_error(resp, ApiErrorId.ERR_MANIFEST_OVERLAP.value)
    after2 = validate_success(api.get_manifest(man2["id"], dist_h()))
    assert after2["line_count"] == 0, "second manifest must gain no line"


# ---------------------------------------------------------------------------
# Rule 9 (compensating_invariant): depart->recall conserves origin custody
# ---------------------------------------------------------------------------
def test_recall_conserves_origin_license_custody(api):
    """PRD §3.6: "A manifest in transit may be recalled back to `DRAFT` by the
    distributor, which clears `departed_at` to null and cascades every line's
    package from `IN_TRANSIT` back to `ACTIVE`, incrementing the manifest's
    `version`"

    Design: Difficulty/compensating_invariant/manifest_depart_recall_conserves_origin_custody
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    validate_success(depart_manifest(man["id"], expected_version=man["version"]))
    validate_success(api.recall_manifest(man["id"], dist_h()))
    data = validate_success(api.get_package(pkg["id"], dist_h()))
    assert data["license_id"] == dist["id"], "origin custody must be conserved on recall"


def test_recall_conserves_package_status_and_remaining(api):
    """PRD §3.6: "cascades every line's package from `IN_TRANSIT` back to
    `ACTIVE`, incrementing the manifest's `version`"

    Design: Difficulty/compensating_invariant/manifest_depart_recall_conserves_origin_custody
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=100)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 100)
    validate_success(depart_manifest(man["id"], expected_version=man["version"]))
    validate_success(api.recall_manifest(man["id"], dist_h()))
    data = validate_success(api.get_package(pkg["id"], dist_h()))
    assert data["status"] == "ACTIVE"
    assert data["remaining_grams"] == 100.0, "remaining grams unchanged after depart/recall"


# ---------------------------------------------------------------------------
# Corner: OCC stale manifest version on depart
# ---------------------------------------------------------------------------
def test_depart_with_stale_manifest_version_rejected(api):
    """PRD §2.10: "Departing a manifest requires the request to carry
    `expected_manifest_version`, which must equal the manifest's current
    `version`."
    PRD §2.10: "In that case the depart is rejected with `ERR_STALE_VERSION`
    (HTTP 412) rather than shipping a stale line set."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_manifest_version_on_depart
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg1 = create_active_package(dist["id"], lab["id"], quantity_grams=50)
    pkg2 = create_active_package(dist["id"], lab["id"], quantity_grams=50)
    man = create_manifest(dist["id"], dest["id"])
    add_manifest_line(man["id"], pkg1["id"], 50)
    stale = validate_success(api.get_manifest(man["id"], dist_h()))
    stale_v = stale["version"]
    # A second line attach bumps the manifest version, making stale_v stale.
    add_manifest_line(man["id"], pkg2["id"], 50)
    resp = api.depart_manifest(man["id"], {"expected_manifest_version": stale_v}, dist_h())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_manifest(man["id"], dist_h()))
    assert after["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: receive accept re-homes custody immediately
# ---------------------------------------------------------------------------
def test_receive_accept_rehomes_package_to_destination(api):
    """PRD §3.6: "On acceptance the manifest moves to the terminal `RECEIVED`
    state, the destination license must be `ACTIVE`, and each line's package has
    its `license_id` re-homed to the destination license and its status set back
    to `ACTIVE`."

    Design: Corner/consistency_model/manifest_receive_accept_immediate_custody_change
    """
    # Origin custodies the package; packages can only originate on a CULTIVATION
    # license (PRD §3.4: a package's license_id is initially the harvest's, and
    # harvests/plant-batches require a CULTIVATION license per §2.7), so the
    # manifest origin here is a cultivation license.
    dist = create_cultivation_license()
    dest = create_cultivation_license()
    lab = create_testing_license()
    pkg = create_active_package(dist["id"], lab["id"], quantity_grams=50)
    man = create_draft_manifest_with_line(dist["id"], dest["id"], pkg["id"], 50)
    validate_success(depart_manifest(man["id"], expected_version=man["version"]))
    received = validate_success(api.receive_manifest(man["id"], {"decision": "accept"}, dist_h()))
    assert received["status"] == "RECEIVED"
    data = validate_success(api.get_package(pkg["id"], dist_h()))
    assert data["license_id"] == dest["id"]
    assert data["status"] == "ACTIVE"
