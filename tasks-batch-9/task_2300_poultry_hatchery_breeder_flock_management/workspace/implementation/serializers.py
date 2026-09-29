"""Entity serializers (scaffold Table 1 field lists + PRD §2.5 common fields)."""

from helpers import COMMON, serialize
import services

FLOCK_PROGRAM_FIELDS = ("id", "code", "breed", "stimulation_week", "lighting_steps",
                        "feed_steps", "retired", "created_at", "updated_at", "version")

INCUBATION_PROFILE_FIELDS = ("id", "code", "breed", "transfer_hours", "total_hours",
                             "stages", "retired", "created_at", "updated_at", "version")

INCUBATION_UNIT_FIELDS = ("id", "code", "unit_type", "capacity_eggs", "sanitation_status",
                          "sanitized_at", "occupancy_status",
                          "created_at", "updated_at", "version")

BREEDER_FLOCK_FIELDS = ("id", "code", "program_id", "source_flock_id", "breed",
                        "house_code", "hatch_date", "placed_at", "hen_count", "status",
                        "age_weeks", "photoperiod_hours", "feed_grams_per_hen_day",
                        "production_rate_pct", "lighting_factor", "nutrition_factor",
                        "settable_forecast", "hatchability_rolling_pct",
                        "hatchability_fertile_pct", "corrective_action_count",
                        "late_pull_count", "egg_hold_opened_by_user_id",
                        "egg_hold_opened_at", "created_at", "updated_at", "version")

EGG_LOT_FIELDS = ("id", "flock_id", "collected_at", "collected_count", "grade_a_count",
                  "cracked_count", "dirty_count", "small_count", "settable_count",
                  "eggs_remaining", "storage_temp_c", "stored_at",
                  "sanitation_cycle_count", "effective_age_days", "status",
                  "condemned_reason", "created_at", "updated_at", "version")

SETTER_LOAD_FIELDS = ("id", "unit_id", "profile_id", "planned_set_at", "set_at",
                      "total_eggs_set", "weighted_age_days", "storage_delay_hours",
                      "planned_transfer_at", "planned_pull_at", "pull_window_start_at",
                      "pull_window_end_at", "fertile_count", "fertility_pct",
                      "deviation_degree_hours", "environment_status",
                      "deviation_opened_at", "status", "abort_reason",
                      "created_at", "updated_at", "version")

SETTER_LOAD_ITEM_FIELDS = ("id", "setter_load_id", "egg_lot_id", "eggs_taken",
                           "effective_age_days_at_set", "item_status",
                           "created_at", "updated_at", "version")

ENVIRONMENT_READING_FIELDS = ("id", "created_at", "setter_load_id", "recorded_at",
                              "temp_c", "humidity_pct", "elapsed_hours",
                              "target_temp_c", "abs_deviation_c",
                              "segment_degree_hours")

HATCHER_LOAD_FIELDS = ("id", "setter_load_id", "unit_id", "transferred_at",
                       "eggs_transferred", "planned_pull_at", "pull_window_start_at",
                       "pull_window_end_at", "inherited_degree_hours", "actual_pull_at",
                       "pull_offset_hours", "pull_class", "quality_flag",
                       "hold_release_at", "status", "created_at", "updated_at",
                       "version")

CHICK_BATCH_FIELDS = ("id", "hatcher_load_id", "primary_flock_id", "breed",
                      "hatched_count", "male_count", "female_count", "unsexed_count",
                      "sexing_cull_count", "preliminary_yield_pct",
                      "vaccine_reject_rate", "vaccine_cull_count", "cull_count",
                      "saleable_count", "final_yield_pct", "box_count",
                      "unassigned_chicks", "quality_score_provisional",
                      "quality_score_final", "status",
                      "created_at", "updated_at", "version")

GROWER_FARM_FIELDS = ("id", "code", "operator_user_id", "capacity_chicks",
                      "biosecurity_status", "cleared_at",
                      "created_at", "updated_at", "version")

PLACEMENT_ORDER_FIELDS = ("id", "farm_id", "requested_breed", "requested_placement_date",
                          "requested_chicks", "allocated_chicks", "remaining_need",
                          "status", "created_at", "updated_at", "version")

DELIVERY_ASSIGNMENT_FIELDS = ("id", "chick_batch_id", "placement_order_id",
                              "chicks_assigned", "boxes_assigned",
                              "scheduled_delivery_date", "delivered_at",
                              "reversal_reason", "status",
                              "created_at", "updated_at", "version")

LAB_TEST_FIELDS = ("id", "subject_type", "subject_id", "test_code", "collected_at",
                   "released_at", "result", "status",
                   "created_at", "updated_at", "version")

CORRECTIVE_ACTION_FIELDS = ("id", "flock_id", "trigger_reason",
                            "observed_hatchability_pct", "opened_at",
                            "opened_by_user_id", "implementation_note",
                            "verification_round", "status",
                            "created_at", "updated_at", "version")


def flock_program(rec):
    return serialize(rec, FLOCK_PROGRAM_FIELDS)


def incubation_profile(rec):
    return serialize(rec, INCUBATION_PROFILE_FIELDS)


def incubation_unit(rec):
    return serialize(rec, INCUBATION_UNIT_FIELDS)


def breeder_flock(rec):
    services.refresh_flock(rec)
    return serialize(rec, BREEDER_FLOCK_FIELDS)


def egg_lot(rec):
    services.refresh_lot(rec)
    return serialize(rec, EGG_LOT_FIELDS)


def setter_load(rec):
    return serialize(rec, SETTER_LOAD_FIELDS)


def setter_load_item(rec):
    return serialize(rec, SETTER_LOAD_ITEM_FIELDS)


def environment_reading(rec):
    return serialize(rec, ENVIRONMENT_READING_FIELDS)


def hatcher_load(rec):
    return serialize(rec, HATCHER_LOAD_FIELDS)


def chick_batch(rec):
    return serialize(rec, CHICK_BATCH_FIELDS)


def grower_farm(rec):
    return serialize(rec, GROWER_FARM_FIELDS)


def placement_order(rec):
    return serialize(rec, PLACEMENT_ORDER_FIELDS)


def delivery_assignment(rec):
    return serialize(rec, DELIVERY_ASSIGNMENT_FIELDS)


def lab_test(rec):
    return serialize(rec, LAB_TEST_FIELDS)


def corrective_action(rec):
    return serialize(rec, CORRECTIVE_ACTION_FIELDS)
