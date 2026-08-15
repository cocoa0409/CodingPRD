"""Replacement-heifer retention: class gate, availability bound, and the
retain/unretain head conservation invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_calf_crop,
    create_herd_group,
    drive_season_to_gestation,
    get_calf_crop,
    get_herd_group,
    setup_ranch_with_group,
    validate_error,
)

HERD_MGR = TEST_USERS["herd_manager_headers"]


def _crop_and_group(steer_head=40, heifer_head=60, repl_head=0,
                    repl_name="Replacement Heifers"):
    """Calf crop (season driven to GESTATION) plus a REPLACEMENT_HEIFER group.
    Retention is not gated on weaning by the PRD."""
    ranch, group = setup_ranch_with_group(head_count=60)
    season = drive_season_to_gestation(ranch["id"], group["id"],
                                       exposed_head_count=50)
    crop = create_calf_crop(season["id"], ranch["id"], steer_head=steer_head,
                            heifer_head=heifer_head)
    repl = create_herd_group(ranch["id"], group_name=repl_name,
                             animal_class="REPLACEMENT_HEIFER",
                             head_count=repl_head, avg_weight_lbs=650)
    return ranch, group, crop, repl


class TestRetentionBounds:
    def test_retention_exceeds_available_rejected(self, api):
        """PRD §3.6: "the count may not exceed the crop's
        `available_heifer_head`, or the retain fails with
        `ERR_RETENTION_EXCEEDS_AVAILABLE` (HTTP 422)."
        PRD §3.6: "Retaining adds the head to the crop's `retained_heifer_head`
        — which lowers `available_heifer_head` by the same amount — and adds
        them to the target group's `head_count`"

        Design: Corner/validations/retention_exceeds_available_rejected
        """
        _ranch, _group, crop, repl = _crop_and_group(heifer_head=60)
        # 61 > 60 available heifers.
        resp = api.retain_heifers(
            crop["id"], {"head_count": 61, "target_herd_group_id": repl["id"]},
            HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_RETENTION_EXCEEDS_AVAILABLE,
                       expected_status=422)
        # Exactly the available count succeeds — the bound is inclusive.
        ok = api.retain_heifers(
            crop["id"], {"head_count": 60, "target_herd_group_id": repl["id"]},
            HERD_MGR)
        assert ok.status_code == 200, f"retain of exactly 60 failed: {ok.text}"
        crop_after = get_calf_crop(crop["id"])
        assert crop_after["available_heifer_head"] == 0
        assert crop_after["retained_heifer_head"] == 60
        assert get_herd_group(repl["id"])["head_count"] == 60

    def test_retention_class_mismatch_rejected(self, api):
        """PRD §3.6: "the target must be a `REPLACEMENT_HEIFER`-class group on
        the same ranch that has not been `LIQUIDATED`, with violations rejected
        as `ERR_RETENTION_CLASS_MISMATCH` (HTTP 422)"

        Design: Corner/validations/retention_class_mismatch_rejected
        """
        _ranch, group, crop, _repl = _crop_and_group(heifer_head=60)
        # The MATURE_COW cow group is not a legal retention target.
        resp = api.retain_heifers(
            crop["id"], {"head_count": 10, "target_herd_group_id": group["id"]},
            HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_RETENTION_CLASS_MISMATCH,
                       expected_status=422)
        assert get_calf_crop(crop["id"])["retained_heifer_head"] == 0


class TestRetainUnretainConservation:
    def test_retain_moves_head_conserving_total(self, api):
        """PRD §3.6: "Retaining adds the head to the crop's
        `retained_heifer_head` — which lowers `available_heifer_head` by the
        same amount — and adds them to the target group's `head_count`; the
        first retention into a group also pins that group's
        `retained_from_crop_id` to the crop's `id`, and that pin is what later
        gates reversal."
        PRD §3.6: "The `available_steer_head` is the `steer_head` minus
        `death_loss_steer_head`, minus `reserved_steer_head`, minus
        `marketed_steer_head`; the `available_heifer_head` subtracts
        `death_loss_heifer_head`, `reserved_heifer_head`,
        `marketed_heifer_head`, and additionally `retained_heifer_head` from the
        `heifer_head`."

        Design: Difficulty/compensating_invariant/heifer_retain_unretain_head_conservation
        """
        _ranch, _group, crop, repl = _crop_and_group(heifer_head=60,
                                                     repl_head=10)
        assert get_herd_group(repl["id"])["head_count"] == 10
        assert get_calf_crop(crop["id"])["available_heifer_head"] == 60

        ok = api.retain_heifers(
            crop["id"], {"head_count": 25, "target_herd_group_id": repl["id"]},
            HERD_MGR)
        assert ok.status_code == 200
        group_after = get_herd_group(repl["id"])
        crop_after = get_calf_crop(crop["id"])
        assert group_after["head_count"] == 35
        assert group_after["retained_from_crop_id"] == crop["id"]
        assert crop_after["retained_heifer_head"] == 25
        assert crop_after["available_heifer_head"] == 35
        # Conserved: 35 in the group + 35 still marketable == 70 tracked heifers.
        assert group_after["head_count"] + crop_after["available_heifer_head"] == 70

    def test_unretain_compensates_with_zero_drift(self, api):
        """PRD §3.6: "Unretaining flows the other way: naming a
        `source_herd_group_id` whose `retained_from_crop_id` must point back at
        this crop, with a `head_count` no greater than the crop's
        `retained_heifer_head` (again `ERR_RETENTION_EXCEEDS_AVAILABLE`); the
        source group's `head_count` and the crop's `retained_heifer_head` both
        fall by the count, returning those heifers to the marketable pool."

        Design: Difficulty/compensating_invariant/heifer_retain_unretain_head_conservation
        """
        _ranch, _group, crop, repl = _crop_and_group(heifer_head=60,
                                                     repl_head=10)
        api.retain_heifers(crop["id"],
                           {"head_count": 25, "target_herd_group_id": repl["id"]},
                           HERD_MGR)
        ok = api.unretain_heifers(
            crop["id"], {"head_count": 10, "source_herd_group_id": repl["id"]},
            HERD_MGR)
        assert ok.status_code == 200
        group_after = get_herd_group(repl["id"])
        crop_after = get_calf_crop(crop["id"])
        assert group_after["head_count"] == 25
        assert crop_after["retained_heifer_head"] == 15
        assert crop_after["available_heifer_head"] == 45
        # 25 + 45 == 70 — the retain/unretain pair leaves zero drift.
        assert group_after["head_count"] + crop_after["available_heifer_head"] == 70
