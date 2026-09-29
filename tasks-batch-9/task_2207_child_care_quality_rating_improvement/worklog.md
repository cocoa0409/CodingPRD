# Worklog — task_2207_child_care_quality_rating_improvement

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2207_child_care_quality_rating_improvement/` and `tasks/task_2207_child_care_quality_rating_improvement/workspace/`.

## Step 3: Copy shared files — 2026-09-01T01:08:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2207_child_care_quality_rating_improvement/workspace/INSTRUCTION.md` (1424 bytes). Run ahead of Step 2's completion since it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-09-01T02:12:00.000Z

**Orchestrator note on execution shape.** The first two attempts to generate all three scaffold artifacts in a single subagent were both killed by the harness stream watchdog ("no progress for 600s"). Transcript forensics showed the same failure mode both times: the agent spent its entire activity budget on prep reads (one attempt read `scaffold_lint.py` three separate times) and then hung composing a single enormous Write, never reaching the first file write. Step 2 was therefore re-split into three smaller sequential/concurrent agents — 2a `SCAFFOLD.yaml` (§1.0–§1.7), then 2b `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) and 2c `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) concurrently off the finished body — each under an explicit incremental-write discipline (first Write within minutes, one section per call, ≤300 lines per payload, no reading the linter's source). Same skill, same verbatim scenario, same no-peeking-at-sibling-tasks constraint.

### Step 2a — SCAFFOLD.yaml (§1.0–§1.7), subagent summary verbatim:

Deliverable complete: `/home/ubuntu/github/CodingPRD/tasks/task_2207_child_care_quality_rating_improvement/SCAFFOLD.yaml` (the only file written; no stub or design files placed in the task directory).

**Counts**
- Entities: **15** — StandardDomain, Provider, RatingCycle, SelfAssessment, StaffCredential, Observer, ObservationVisit, ObservationScore (`common_fields: false`, append-only with `attempt_no`/`is_current`), Appeal, DataDispute, ImprovementGrant, GrantExpenditure, CoachingAllocation, CoachingSession, SubsidyClaim
- State machines: **7** — Provider, RatingCycle (11 states, cyclic AWARDED→UNDER_APPEAL→AWARDED plus two revision loops), ObservationVisit (fork-join into FINALIZED via reliability-check vs single-observer branch, with rescore loop), Appeal (UNDER_REVIEW↔INFO_REQUESTED), DataDispute (TRIAGE↔ESCALATED/INFO_REQUESTED), ImprovementGrant (with independent `parallel_dimension: compliance_status` axis), SubsidyClaim (PAID→RECONCILE_REQUIRED→PAID)
- Calculation rules: **10** — credential_compliance_pct, observation_composite_score, inter_rater_reliability_pct, domain_points_award (PROVISIONAL/FINAL), rating_tier_determination (PROVISIONAL/FINAL), validity_period, subsidy_reimbursement (INTERIM/RECONCILED), grant_reimbursement_waterfall, coaching_allocation_cost, grant_compliance_recovery
- Endpoints: **69** (includes `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default, and `POST /qris/expiry-runs`)
- Error catalog: **55** entries
- Also: 43 ordered validations (priorities 1–63), 2 OCC concurrency rules, 6 roles (segregation-of-duties: AppealReviewer must differ from `RatingCycle.awarded_by_user_id`)

**Confirmation:** neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears — top-level keys are exactly `scenario, domain_name, api_prefix, api_prefix_note, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`.

**Validation status:** YAML parses cleanly; `scaffold_lint.py` returns `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (run in a temp dir with empty design stubs, since the linter requires the sibling files that the other two agents produce). No forbidden concurrency vocabulary present; the sole `parallel` match is the structural `parallel_dimension:` key.

Two notes for the sibling agents: `api_prefix` is `"/"` (peer collections at root, e.g. `/providers`, `/rating-cycles`) — required for the linter's FK reverse-reachability heuristic to resolve; and every FK-child entity has a single-resource GET (`/self-assessments/{self_assessment_id}`, `/observation-scores/{observation_score_id}`, etc.) they can cite in §1.8/§1.9 calls. Final polish applied this turn: the SubsidyClaim `RECONCILE_REQUIRED -> PAID` precondition no longer self-references the recomputed variant; it now checks `claim.status == RECONCILE_REQUIRED`, non-null `provider.current_tier`, and no open Appeal on the covering rating cycle.

### Step 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)

**Two further watchdog kills before this file was produced.** A dedicated §1.8 agent stalled after reading SKILL.md + the whole 2883-line SCAFFOLD.yaml. Its retry — under an explicit heartbeat-and-sliced-reads discipline — behaved correctly (22 tool calls, heartbeat echoes, `sed`-sliced scaffold reads) and still died: it consumed its entire activity budget reading the scaffold in slices and was killed just as it began its first write. Diagnosis: §1.8 for this scaffold (9 rules × ≥3 instances, each requiring verified multi-step arithmetic against 10 formulas) is too large for one agent regardless of write discipline. Step 2b was therefore **sharded into three agents of three rules each**, writing standalone fragments to `/tmp/task2207_frag/`, which the orchestrator merged. All three shards succeeded on the first try, confirming the load — not the discipline — was the binding constraint.

Shard→rule assignment: **A** = dual_variant_calc, combinatorial_formula, boundary_precision_check (calculation/boundary-centric); **B** = non_linear_state_machine, transitive_cascade, cross_entity_state_dependency (state-machine/cascade-centric); **C** = priority_pair_validation_conflict, resource_temporal_overlap, compensating_invariant (validation/interval/conservation-centric).

**Merge performed by the orchestrator** via raw-text concatenation of rule blocks (not a YAML round-trip, to preserve each author's computed literals and comments byte-for-byte), re-ordered into canonical §0.5 rule order 1–9. Post-merge verification: single top-level key; 9 rules; **32 instances**; 0 duplicate instance names; 0 `round(...)` expressions in any assert.

One merge-time issue found and resolved: shard B warned that `LIC-2207-*` license numbers might collide across fragments against the priority-9 global-uniqueness validation. Audit found 9 license values reused across fragments but **0 collisions within any single instance** — and since every instance's `setup_api_calls` drives an empty DB under per-test-server isolation, cross-instance reuse is harmless. No change made.

#### Shard A summary verbatim:

Fragment complete at `/tmp/task2207_frag/difficulty_A.yaml` (1586 lines, parses cleanly, single top-level key `scaffold_difficulty_design`).

**Rule ids and instance counts — 10 instances total**

`dual_variant_calc` (3) — each on a different entity domain:
1. `provisional_vs_final_domain_points_on_rating_cycle` — RatingCycle/SelfAssessment scoring. PROVISIONAL preview 86.00/tier 5 vs FINAL award 77.50/tier 4; domain_points {LE 32, SQ 24, FP 15, AD 14, CA 8}; validity 36 mo, effective 2026-09-01, expires 2029-08-31T23:59:59.999Z, rerating 2029-06-02.
2. `interim_vs_reconciled_subsidy_multiplier_on_subsidy_claim` — SubsidyClaim fiscal. base 424400; INTERIM ×1.15 (FRONTIER 1.15, tier 3) → 561270 (per-band round-then-sum; sum-then-round = 561269); after Appeal SUSTAINED to tier 5 + expiry-run re-promotion, RECONCILED → 732090, delta 170820.
3. `fee_on_base_vs_fee_on_total_coaching_cost` — CoachingAllocation funding. 15.5 h × 12261 = 190045.5 → base 190046, fee band 0.09 → 17104, total 207150; fee-on-total reading gives 201449 (5701-cent divergence).

`combinatorial_formula` (3) — one per mode, no collision:
1. `mode_a_nested_min_over_sequential_block_fold` (mode a, ≥3 interacting inputs) — weighted 96.17, points_tier 5, block fold CLEARED/NOT_CLEARED/CLEARED → highest_block_cleared 1 → BLOCK_CAP_TIER awarded_tier 2, validity 24 mo, expires 2028-08-31.
2. `mode_b_pinned_round_before_min_in_grant_waterfall` (mode b, nested rounding order) — grant 1000000; reimbursable 11111/30000/16667/5000 → reimbursed 62778 (round-after-sum would give 62777), available 937222.
3. `mode_c_pinned_order_compliance_points_tier_then_tier_keyed_gate` (mode c, circular-looking with pinned order) — credential expiry between finalize (compliance 95.00) and award (85.00) flips SQ cap 30→24, weighted 73.00→68.00, tier 3, gate MIN_COMPLIANCE_BY_TIER[3] = 80.00 passes where the stale path would raise ERR_CREDENTIAL_COMPLIANCE_BELOW_MINIMUM.

`boundary_precision_check` (4) — 6 boundary metrics across 4 distinct endpoints:
1. `reliability_pct_inclusive_at_exactly_83_33` — `POST /observation-visits/{id}/finalize`; 66.67 → 422 ERR_RELIABILITY_BELOW_THRESHOLD, rescore → exactly 83.33 → succeeds, composite 5.00.
2. `weighted_total_exactly_at_tier_4_cutoff_and_compliance_floor` — `POST /rating-cycles/{id}/award`; compliance exactly 90.00 == MIN_COMPLIANCE_BY_TIER[4], weighted exactly 70.00 → tier 4, validity 36 mo.
3. `coaching_hours_cap_inclusive_and_admin_fee_band_strict_less_than` — `POST /providers/{id}/coaching-allocations`; 40.0 h accepted at COACHING_HOURS_CAP[1] (base 50000 → 0.09 → fee 4500, total 54500), 40.1 h → 422 ERR_COACHING_HOURS_CAP_EXCEEDED, base 49999 → 0.12 → fee 6000, total 55999 (1500-cent shift across a 1-cent band edge); spend_cap 500000.
4. `grant_category_ceiling_floor_and_available_cents_zero_edge` — `POST /improvement-grants/{id}/expenditures`; award 1000005 → floor ceilings 400002/300001/250001/100000; 300002 → 422 ERR_GRANT_CATEGORY_CEILING_EXCEEDED, 300001 accepted (inclusive `<=`), fourth line drives available_cents to exactly 0 (committed 1000005), then 1 cent → 422 ERR_GRANT_FUNDS_EXHAUSTED.

**Calculations grounded against:** `domain_points_award`, `rating_tier_determination`, `validity_period`, `observation_composite_score`, `inter_rater_reliability_pct`, `credential_compliance_pct`, `subsidy_reimbursement`, `grant_reimbursement_waterfall`, `coaching_allocation_cost`; validations p11/p20/p21/p22/p24/p27/p30/p47/p52/p57/p60/p61/p63; Appeal SUSTAINED cascade and `POST /qris/expiry-runs`.

Verified mechanically: names unique (10), every `${var}` bound by an earlier `captures:`, no `round(...)`/`floor(...)`/`Decimal` expressions in any assert (all numeric asserts are literals computed with Decimal/ROUND_HALF_UP via `python3 -c`). Only `/tmp/task2207_frag/difficulty_A.yaml` was written; no task-directory files touched, `scaffold_lint.py` neither read nor run.

#### Shard B summary verbatim:

Fragment complete and validated at `/home/ubuntu/github/CodingPRD` → output file `/tmp/task2207_frag/difficulty_B.yaml`.

**Validation output**
```
['scaffold_difficulty_design'] [('non_linear_state_machine', 4), ('transitive_cascade', 4), ('cross_entity_state_dependency', 3)]
total 11
```
Also checked mechanically: 0 unbound `${var}` references (every one traced to an earlier `captures:` in the same recipe, asserts included) and 0 `round(` expressions anywhere — all numeric asserts are literals computed via `python3`.

**Rule ids and instances (11 total)**

`non_linear_state_machine` (4) — one per distinct entity:
- `rating_cycle_awarded_under_appeal_awarded_cycle` (RatingCycle cycle AWARDED→UNDER_APPEAL→AWARDED)
- `observation_visit_fork_join_with_reliability_rescore_loop` (ObservationVisit fork-join + RELIABILITY_CHECK↔SCORES_ENTERED loop, two providers C/D for the two arms)
- `improvement_grant_orthogonal_compliance_axis` (ImprovementGrant `status` × `compliance_status` parallel dimension, incl. REMEDIATED→UNDER_REVIEW cycle)
- `appeal_under_review_info_requested_bidirectional_rounds` (Appeal UNDER_REVIEW↔INFO_REQUESTED, 2-round limit)

`transitive_cascade` (4) — four different triggering transitions, two of depth ≥ 3:
- `appeal_sustain_tier_to_claim_to_provider_adjustment_chain` (Appeal SUSTAIN → cycle tier → PAID claim RECONCILE_REQUIRED → provider adjustment; depth 3)
- `cycle_expiry_four_hop_provider_allocation_grant_leaf_chain` (expiry run → publication WITHDRAWN → provider tier null → allocation SUSPENDED / grant FROZEN → session CANCELLED / expenditure VOIDED; depth 4)
- `provider_suspend_three_hop_publication_allocation_session_chain` (Provider status-change → publication → allocation → session)
- `grant_close_recovery_compliance_to_provider_adjustment_chain` (grant close with recovery → compliance FINDING_ISSUED→RECOVERY → provider adjustment; allocations CLOSED)

`cross_entity_state_dependency` (3) — three different entity pairs:
- `staff_credential_registry_state_gates_rating_cycle_award` — RatingCycle → StaffCredential (registry_status drives `credential_compliance_pct` vs `MIN_COMPLIANCE_BY_TIER[4] == 90.00`)
- `open_appeal_state_gates_subsidy_claim_reconciliation_payment` — SubsidyClaim → Appeal, on the `RECONCILE_REQUIRED → PAID` edge, which names no RatingCycle status at all, so a sibling Appeal in FILED is the *only* possible blocker; withdrawing it makes the byte-identical `pay` succeed and rewrites `reimbursement_cents` 3046680 → 3515400 (base 2170000, multiplier 1.3000 → 1.5000, provider adjustment 468720 → 0)
- `observer_reliability_state_gates_observation_visit_finalization_and_scoring` — ObservationVisit → Observer; a sub-threshold `CERTIFY 82.00` flips the secondary to LAPSED and blocks both `finalize` and a rescore by the still-RELIABLE **lead** (priority 20 tests every observer named on the visit, not the acting one); re-certification unblocks and the award lands at `weighted_total 80.00`, `points_tier 4`, `awarded_tier 4`, `highest_block_cleared 3`, domain_points {24,20,16,12,8}

**State machines grounded against:** RatingCycle, ObservationVisit, Appeal, ImprovementGrant (both `status` and the `compliance_status` parallel dimension), SubsidyClaim, Provider, plus the CoachingAllocation/CoachingSession and GrantExpenditure leaves reached by cascade. Calculations grounded: `rating_tier_determination`, `domain_points_award`, `validity_period`, `inter_rater_reliability_pct`, `observation_composite_score`, `credential_compliance_pct`, `subsidy_reimbursement`, `grant_reimbursement_waterfall`, `grant_compliance_recovery`.

**Notes for the merge:** all 11 instances use distinct providers (letters A, C–M with distinct `license_number` `LIC-2207-<X>`), so the fragment has no id collisions internally; if the other two shards also use `LIC-2207-*` license numbers, check for duplicates against the global-uniqueness validation (priority 9).

#### Shard C summary verbatim:

Fragment complete and validated at `/home/ubuntu/github/CodingPRD` scope-safe path **`/tmp/task2207_frag/difficulty_C.yaml`** (the only file written; nothing in the task directory touched, `scaffold_lint.py` neither read nor run).

Finish command output:
```
['scaffold_difficulty_design'] [('priority_pair_validation_conflict', 4), ('resource_temporal_overlap', 4), ('compensating_invariant', 3)]
```

Total: **11 instances** (4 / 4 / 3), all three assigned rule_ids and no others.

Post-edit re-validation (all clean):
- YAML parses; every rule block has exactly `{rule_id, instances}`; every instance exactly `{name, grounds, distinguishing_aspect, test_recipe}`; every `test_recipe` exactly `{setup, setup_api_calls, trigger, assert}`.
- Every call object uses only `{call, payload, as, as_user_id, captures}`; every `${var}` in any call or assert is bound by an earlier `captures:`; no `round(` in any assert.
- **Grounds resolution check against SCAFFOLD.yaml: 0 dangling refs** — all `validations[priority=N]`, `calculations.X`, `entities.E.fields.f`, and `state_machines.E.A_to_B` entries resolve (this confirms the two late fixes that replaced the nonexistent `state_machines.CoachingSession.*` / unexercised `ImprovementGrant.OPEN_to_FROZEN` refs).

### priority_pair_validation_conflict (4) — each a distinct error-category pair
| instance | pair (category / priority / error / status) |
|---|---|
| `forbidden_role_beats_cycle_state_on_award` | auth **p2** `ERR_FORBIDDEN_ROLE` 403 **beats** state **p10** `ERR_CYCLE_STATE_INVALID` 409 |
| `path_not_found_beats_body_schema_on_visit_scheduling` | existence **p3** `ERR_RATING_ARTIFACT_NOT_FOUND` 404 **beats** business_constraint **p6** `ERR_VALIDATION` 422 |
| `observer_reliability_beats_schedule_conflict` | business_safety **p20** `ERR_OBSERVER_NOT_RELIABLE` 422 **beats** business_temporal **p41** `ERR_OBSERVER_SCHEDULE_CONFLICT` 409 |
| `grant_not_open_beats_funds_exhausted` | state **p10** `ERR_GRANT_NOT_OPEN` 409 **beats** business_fiscal **p61** `ERR_GRANT_FUNDS_EXHAUSTED` 422 (correct `expected_grant_version` keeps OCC p8 inert) |

Other priorities exercised/kept inert across the fragment: 8, 25, 26, 27, 40, 42, 43, 45, 50, 52, 57, 60, 63.

### resource_temporal_overlap (4) — each a different interval semantics, all clock-driven via `POST /_clock/set_current_utc`
1. `observer_half_open_window_adjacency_across_providers` — **half-open `[window_start, window_end)`** (p41): start exactly at `2026-08-10T17:00:00Z` → 201; `16:59:59Z` → 409.
2. `observer_same_provider_48h_cooldown_buffer` — **buffered interval, strict `<`**: geometrically disjoint `2028-06-12T08:00:00Z` → 409 (inside prior end + 48h); `2028-06-12T17:00:00Z` → 201. Routed award → expiry-run → clock 2028-06-02 → RERATING cycle so p10/p50 stay inert and p43's inclusive boundary is hit.
3. `coaching_site_closed_interval_touching_endpoints` — **closed `[scheduled_start, scheduled_end]`** (p42): touching endpoint `2026-09-14T12:00:00Z` → 409 `ERR_ONSITE_CAPACITY_CONFLICT`; `13:00:00Z` → 201.
4. `onsite_weekly_aggregate_capacity_bucket` — **aggregate ISO-week bucket** `2026-W38` across two allocations: 5.0+4.0+4.5 = 13.5 > 12.0 → 409; +3.0 landing exactly on 12.0 → 201 (reject only when strictly greater).

### compensating_invariant (3) — three different conserved quantities, both sides as computed literals
1. `grant_funds_conserved_across_submit_then_reject` — **grant funds identity** `awarded = committed + reimbursed + available`: `250000+300000+450000 == 1000000`, then after REJECT `0+300000+700000 == 1000000`; EQUIPMENT category_spend returns to 0, PROF_DEV stays 300000.
2. `coaching_hours_conserved_across_schedule_then_cancel` — **coaching-hours ledger** `allocated = scheduled + delivered + remaining`: `4.0+3.5+4.5 == 12.0`, then `0.0+3.5+8.5 == 12.0`; `total_cost_cents 117720` unchanged, delivered 3.5 permanently consumed.
3. `subsidy_adjustment_conserved_across_interim_then_reconciled_pay` — **subsidy dollars parked on `Provider.reimbursement_adjustment_cents`**: INTERIM tier-2 multiplier 1.0500 → 311850; Appeal SUSTAIN with `adjusted_tier: 1` parks `-14850`; expiry-run returns cycle to ACTIVE at current_tier 1; RECONCILED pay → multiplier 1.0000 → 297000 and adjustment back to 0, with `297000 - 311850 == -14850`.

All numeric literals were computed with `python3 -c` using `decimal` + `ROUND_HALF_UP` against the scaffold's §1.5 formulas (composite 4.00; credential_compliance_pct 0.00/80.00; domain caps 4/12/12; weighted_total 37.00→tier 1 and 54.00→tier 2 with PROVISIONAL 35.00/52.00; validity 2026-09-01 / 2028-08-31T23:59:59.999Z / rerating opens 2028-06-02; coaching 108000+9720=117720, 98100, 78480; subsidy bands 102060+64638+145152=311850 and 97200+61560+138240=297000).

### Step 2c — SCAFFOLD_CORNER_DESIGN.yaml (§1.9), subagent summary verbatim:

The deliverable is complete and verified.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2207_child_care_quality_rating_improvement/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:** 1 top-level key (`scaffold_corner_design`), 9 sections, **63 instances, all 63 non-stub** (no `excluded_because:` stubs — the §1.8 file wasn't available to cross-reference, so every claim is fully specified). Per-section: entities 12, state_machines 12, calculations 10, validations 10, endpoints 3, errors 4, rbac 5, cross_cutting_layers 5, consistency_model 2.

**Verification:**
- `yaml.safe_load` → exactly one top-level key; all required per-instance keys (`name`, `claim_type`, `grounds`, `distinguishing_aspect`, `test_recipe.{setup,setup_api_calls,trigger,assert}`) present; no duplicate names.
- Placeholder-closure audit across all 63 instances: **0 unbound `${var}` references** in `call`/`payload`/`as_user_id`/`assert` — every placeholder is bound by an earlier `captures:` in the same instance.
- `scaffold_lint.py` run in a temp dir (SCAFFOLD.yaml + my file + a throwaway minimal §1.8 placeholder; nothing written into the real task dir): **clean lint** — 69 endpoints, 15 entities, 63 §1.9 instances, **1128 calls scanned**, all conforming to §1.5 with FK reverse-reachability satisfied.
- SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml were never touched; no sibling task directory was read.

**Validation-precedence surface (chained conflicts, higher-priority error asserted):** p2>p3, p3>p4, p4>p6, p6>p7, p8(stale version)>p43 & p50, p9>p10, p26(registry-unlinked)>p52(block gate), p47(claim month not covered)>p58(zero service units).

**Inclusive/exclusive boundaries:** IRR 83.33 admissible at the inclusive threshold; p41 observer half-open intervals (back-to-back touch allowed, one-second overlap rejected) plus the same-provider-only 48h buffer; p42 closed coaching intervals (touching sessions conflict) under the weekly `iso_week_key` cap; p44 publication quiet period day 10 inclusive; p60 category ceiling accepted exactly then rejected at +$0.01; p61 funds exhausted after four ceilings consume the award; credential `expires_on` inclusive (50.00→25.00); weighted_total exactly 70.00 → tier 4 / 36 months; `expires_on` 2028-08-31T23:59:59.999Z and rerating window 2028-06-02; effective_date = 1st of the month after award.

**Other targeted mechanics:** append-only ObservationScore (`attempt_no`/`is_current`, no `version` field, rescore loop, cancel un-currents all scores); cyclic Appeal (UNDER_REVIEW↔INFO_REQUESTED, DENY restores AWARDED + republished listing) and DataDispute (TRIAGE↔ESCALATED with round increment only); both OCC rules (`rating-cycle-create-stale-provider`, `expenditure-create-stale-grant`) with `"${gv1} - 1"`-style deliberate staleness; 3- and 4-hop cascades; ImprovementGrant's parallel `compliance_status` axis; dual-variant PROVISIONAL preview (100.00/50.00) vs FINAL award (26.00) on the same cycle; sequential block folding proving block 3 cannot rescue the tier cap.

**Errors asserted (24 distinct ids):** ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER, ERR_SEGREGATION_OF_DUTIES, ERR_VALIDATION, ERR_DUPLICATE_RESOURCE, ERR_STALE_VERSION, ERR_PROVIDER_NOT_FOUND, ERR_RATING_ARTIFACT_NOT_FOUND, ERR_OBSERVER_NOT_FOUND, ERR_REMEDY_NOT_FOUND, ERR_FUNDING_NOT_FOUND, ERR_CREDENTIAL_NOT_FOUND, ERR_PROVIDER_STATE_INVALID, ERR_CYCLE_STATE_INVALID, ERR_VISIT_STATE_INVALID, ERR_CREDENTIAL_REGISTRY_UNLINKED, ERR_OBSERVER_SCHEDULE_CONFLICT, ERR_ONSITE_CAPACITY_CONFLICT, ERR_SESSION_OUTSIDE_ALLOCATION_PERIOD, ERR_PUBLICATION_QUIET_PERIOD, ERR_CLAIM_MONTH_NOT_COVERED, ERR_GRANT_CATEGORY_CEILING_EXCEEDED, ERR_GRANT_FUNDS_EXHAUSTED.

**RBAC surface:** peer-role fencing across all six roles' exclusive operations; Observer visit-membership (uninvolved observer blocked, named observer may score but not finalize); Coach `coach_user_id` mismatch rejected before period checks; shared credential creation vs admin-only registry-link; and both segregation-of-duties clauses — the awarding user cannot review the appeal, and no unassigned reviewer can act after assignment.

### Step 2 — final orchestrator verification

`scaffold_lint.py` on the assembled task directory (all three files in place):

```
  §1.5 endpoints declared:    69
  §1.1 entities declared:     15
  §1.8 instances scanned:     32
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  2201

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Reaching clean lint required one rename. The linter reported `(b) role not allowed by §1.5` on §1.8 instance `forbidden_role_beats_cycle_state_on_award` (`as: Provider` on `POST /rating-cycles/{id}/award`, which §1.5 restricts to `StateAdministrator`). Inspection confirmed this is a legitimate negative test — it asserts `HTTP 403` / `ERR_FORBIDDEN_ROLE` and that the cycle stays `DRAFT`. The linter exempts negative triggers from checks (b)/(c) via a name-pattern regex requiring a leading underscore before `forbidden`, which `forbidden_role_beats_...` (leading position) did not match. The instance was renamed to **`award_by_forbidden_role_beats_cycle_state`**, which matches the `_forbidden` pattern. No assertion, payload, role, or arithmetic was altered — the fix was purely to the instance's `name`, so the test's semantics are unchanged.

## Step 4: Generate PRD — 2026-09-01T04:05:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2207_child_care_quality_rating_improvement/workspace/PRD.md` — **438 lines**, ending at §5 with no audit footer.

**Section list**
- §1 Introduction (3 paragraphs)
- §2: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim canonical block) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versioning · 2.5 Optimistic Concurrency on Cycle Opening and Grant Spending · 2.6 Path Resolution and the Not-Found Families · 2.7 The Order in Which a Request Is Rejected · 2.8 The Logical Clock · 2.9 Money, Hours and Rounding Conventions · 2.10 Conservation and Cascade Discipline
- §3 (9 subsections): 3.1 Configuring the Standards and Enrolling a Provider · 3.2 Staff Credentials and the Professional Development Registry · 3.3 Opening a Rating Cycle and Verifying the Self-Assessment · 3.4 On-Site Observation, Observer Reliability, and Score Admission · 3.5 Turning Points Into a Tier: Domain Awards, Block Gates and Validity · 3.6 Publishing to Families, Appeals, and Disputes of Published Data · 3.7 Tiered Subsidy Reimbursement and Retroactive Reconciliation · 3.8 Improvement Grants, Expenditure Compliance and Recovery · 3.9 Coaching Allocations and the On-Site Hours Ledger
- §4 Endpoint Definitions (4-column table, 69 rows) · §5 Error Code Catalogue (2-column table, 55 rows)

**Scaffold coverage:** 15 entities (126 field names) · 7 state machines / 62 transitions incl. the grant's 5-transition parallel compliance dimension · 10 calculations (all formulas in prose, single-rounding and pinned-rounding regimes stated) · 43 ordered validations (global 1–11 ladder in §2.7; per-endpoint orderings stated for cycle-open, finalize, award, publish, claim-adjudicate, expenditure-submit, session-schedule, allocation-create) · 69 endpoints · 55 errors (all referenced in §2/§3 narrative) · 6 roles with every `identity:` translated · 2 OCC rules (`expected_provider_version`, `expected_grant_version`, both `ERR_STALE_VERSION` / 412).

```
Field coverage check:
- entities[].fields: 126 required, 126 present, 0 missing
- endpoints[].request_body: 69 required, 69 present, 0 missing
- endpoints[].query_params: 32 required, 32 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 43 checked, 43 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 62 checked, 62 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing
- entities[].fields[] structured content: 126 checked, 126 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (visit finalize A/B, cycle SUSTAIN/DENY/WITHDRAW restore, provider SUSPEND/REINSTATE/WITHDRAW, grant ACCEPT/DECLINE/REMEDIATE/REOPEN, subsidy INTERIM/RECONCILED, scoring PROVISIONAL/FINAL), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 990
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §2.2 matches the canonical `section-2.2-response-structure.md` byte-for-byte (substring check); all state enumeration values and all enum-field values appear verbatim; the withheld difficulty/corner design files were never opened, and no sibling task was read.

## Resume assessment — 2026-09-01T05:10:00.000Z

A previous run of this task crashed partway through. Re-verified every artifact on disk for completeness (not mere presence) before resuming:

| Artifact | Verdict | Evidence |
|---|---|---|
| `SCAFFOLD.yaml` | **VALID** | 151 899 B, parses, 69 endpoints / 15 entities / 55 errors, top-level keys exclude both design keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **VALID** | 374 246 B, parses, single top-level key, 9 rules / 32 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **VALID** | 332 542 B, parses, single top-level key, 9 sections / 63 instances |
| `workspace/INSTRUCTION.md` | **VALID** | 1 424 B, matches project root copy |
| `workspace/PRD.md` | **VALID** | 438 lines, 107 395 B, terminates cleanly at the §5 error table's final row (`ERR_PROVIDER_UNRATED`), no truncation |
| `test_helpers/` | **VALID** | all 9 modules present and non-empty, `py_compile` clean; `fixtures.py` exposes the full 40-helper surface through `build_rating_spine` and the per-domain setup helpers |
| `test_suite/` | **INCOMPLETE** | only `conftest.py` + `test_10_dual_variant_scoring.py` (7 test functions). Covers all 3 `dual_variant_calc` instances; **92 of 95 design instances have no test** |
| `workspace/implementation/` | **INCOMPLETE** | all 10 shared modules complete and `py_compile` clean (all 10 calculations, all cascades, all 15 serializer kinds, full 57-entry error catalogue, 6 roles). `routes/system.py` + `providers.py` + `cycles.py` implement 25 endpoints. **`routes/observation.py`, `remedy.py`, `funding.py`, `coaching.py`, `claims.py` are 3-line blueprint stubs — 44 of 69 endpoints missing** |
| `workspace/PRD_FINALIZED.md` | ABSENT | Step 8 never reached |
| `workspace/PRD_COMPLETED.md` | ABSENT | Step 9 never reached |

**Resume point: Steps 5 and 6, both partially complete.** Steps 1–4 accepted as-is and not redone. The existing task directory and its name are preserved.

**Sharding decision.** The Step 2 history in this worklog records five separate watchdog kills from single agents attempting too much work per invocation, resolved only by sharding. Steps 5 and 6 are of comparable size (92 test instances; 44 endpoints), so both were sharded from the outset rather than retried monolithically. Seven agents were launched concurrently in a single message:

- **6a** → `routes/observation.py` (11 eps) + `routes/remedy.py` (9 eps)
- **6b** → `routes/funding.py` (10) + `routes/coaching.py` (9) + `routes/claims.py` (5)
- **5a** → queue A `combinatorial_formula` / `non_linear_state_machine` / `transitive_cascade` (11 instances) → `test_11`–`test_13`
- **5b** → queue A `priority_pair_validation_conflict` / `boundary_precision_check` / `cross_entity_state_dependency` / `resource_temporal_overlap` / `compensating_invariant` (18) → `test_14`–`test_18`
- **5c** → queue B `entities` + `state_machines` (24) → `test_20`, `test_21`
- **5d** → queue B `calculations` + `validations` (20) → `test_22`, `test_23`
- **5e** → queue B `endpoints` + `errors` + `rbac` + `cross_cutting_layers` + `consistency_model` (19) → `test_24`–`test_26`

Two conflict-avoidance rules were imposed because the shards run concurrently over shared files:
1. The 10 shared implementation modules (`store`, `errors`, `auth`, `response`, `serializers`, `validation`, `lookups`, `calculations`, `cascades`, `app`) are **read-only** to both impl shards; a shard needing a missing helper defines a private `_`-prefixed function inside its own route module.
2. `test_helpers/` is **read-only** to all five test shards; a shard needing a missing setup helper defines a private `_`-prefixed function inside its own test file.

Each test shard received a **pre-sliced design fragment** under `/tmp/task2207_step5/` holding only its own rules/sections, so no shard loads the 707 KB of design YAML it does not own. Isolation constraints were carried over verbatim: impl shards may not read `test_suite/`, `test_helpers/`, or either design file; test shards may not read `workspace/implementation/`.

## Step 6: Generate implementation (completion of crashed run) — 2026-09-01T04:15:00.000Z

Run as two concurrent shards over the 44 missing endpoints. The 10 shared modules were already complete from the crashed run and were held read-only; both shards wrote only their own route modules and added no shared-module edits and no seeded data.

### Step 6a — routes/observation.py + routes/remedy.py, subagent summary verbatim:

Both deliverables are complete, compile clean, and pass end-to-end runtime verification.

## Files written (only these two)

**`/home/ubuntu/github/CodingPRD/tasks/task_2207_child_care_quality_rating_improvement/workspace/implementation/routes/observation.py`** — 479 lines, blueprint `"observation"`, 11 endpoints:
`POST /observers` · `GET /observers` · `POST /observers/<observer_id>/reliability-certifications` · `POST /rating-cycles/<rating_cycle_id>/observation-visits` · `GET /observation-visits` · `GET /observation-visits/<observation_visit_id>` · `POST /observation-visits/<observation_visit_id>/scores` · `GET /observation-scores` · `GET /observation-scores/<observation_score_id>` · `POST /observation-visits/<observation_visit_id>/finalize` · `POST /observation-visits/<observation_visit_id>/cancel`

**`.../routes/remedy.py`** — 418 lines, blueprint `"remedy"`, 9 endpoints:
`POST /rating-cycles/<rating_cycle_id>/appeals` · `GET /appeals` · `GET /appeals/<appeal_id>` · `POST /appeals/<appeal_id>/review-actions` · `POST /appeals/<appeal_id>/provider-actions` · `POST /rating-cycles/<rating_cycle_id>/data-disputes` · `GET /data-disputes` · `GET /data-disputes/<data_dispute_id>` · `POST /data-disputes/<data_dispute_id>/triage-actions`

No other file was touched; no data is seeded. Only private `_`-prefixed helpers were added inside the two modules.

## Boot check
`python3 -m py_compile` → COMPILE_OK. Server boots on `PORT=18871`; the mandated curl returns **422** `{"error_id":"ERR_VALIDATION","message":"full_name is required"}` inside a well-formed envelope — routes registered.

## Runtime verification (three scripted flows against fresh servers)
- **Happy path**: domains → provider → credentials/registry → enroll → cycle → self-assessment → verify → two observers certified → visit scheduled → 6+6 subscale scores (auto-advance `SCHEDULED→IN_PROGRESS→SCORES_ENTERED`(composite)`→RELIABILITY_CHECK`(reliability 100.00)) → finalize (cycle `OBSERVATION_FINALIZED`, composite propagated) → award tier 5 → publish → appeal filed (cycle `UNDER_APPEAL`/`SUPPRESSED`, listing hidden) → SoD rejections → info round → provider respond → SUSTAIN tier 3 (cycle back to `AWARDED`, `appeal_adjusted=true`, `publication_status=UNPUBLISHED`, original `effective_date` kept, `expires_on` recomputed) → dispute triage → correction applied to provider `licensed_capacity` → tier dispute correctly links the sustained appeal.
- **Observation edges**: cross-provider overlap → `ERR_OBSERVER_SCHEDULE_CONFLICT`; touching windows allowed (half-open); secondary-observer conflict caught; `CANCELLED` visits stop occupying the calendar; lapsed observer → `ERR_OBSERVER_NOT_RELIABLE`; unknown FK → 404 before state; `lead == secondary` → `ERR_VALIDATION`; score before `window_start` → `ERR_VISIT_STATE_INVALID`; non-named observer → `ERR_NOT_RESOURCE_OWNER`; append-only rows verified (`[(1,False,3.0),(2,True,6.0)]`); rescore rounds 1 and 2 admitted, round 3 → `ERR_RESCORE_LIMIT_EXCEEDED`; reliability below threshold blocks finalize; cancel un-currents all rows and rolls the cycle back to `DOCS_VERIFIED`; single-observer visit with provisional tier ≥ 4 → `ERR_SECONDARY_OBSERVER_REQUIRED`.
- **Remedy edges**: SUSTAIN before START → `ERR_APPEAL_STATE_INVALID`; same-tier SUSTAIN → `ERR_VALIDATION`; info rounds 1-2 allowed, 3rd → `ERR_APPEAL_INFO_ROUND_LIMIT`; WITHDRAW and DENY both restore the cycle to `ACTIVE`; filing past day 30 → `ERR_APPEAL_FILING_WINDOW_CLOSED`; triage against an unpublished cycle → `ERR_CYCLE_STATE_INVALID`; `triage_round` increments only on entries into TRIAGE, 4th → `ERR_DISPUTE_TRIAGE_LIMIT`; ESCALATE outside TRIAGE → `ERR_DISPUTE_STATE_INVALID`; provider-only WITHDRAW / admin-only other actions → `ERR_FORBIDDEN_ROLE`.

## PRD vs SCAFFOLD divergences (PRD followed in each case)
1. **Secondary-observer gate at finalize** — PRD §3.4 says "the tier implied by a provisional tier-determination run be no greater than 3"; I compare the provisional run's `awarded_tier` (not `points_tier`), matching both the PRD's later sentence ("a visit whose provisional run implies a tier of 4 or higher") and `cycles.py`'s award-time check.
2. **Finalize ordering** — cycle state (`ERR_CYCLE_STATE_INVALID`) is checked before visit state, per PRD §3.4's "Both branches require the parent cycle to be in `OBSERVATION_SCHEDULED` ... and a visit in any state other than the two branch origins is refused".
3. **SCORES_ENTERED visit that names a secondary** — the single-observer branch requires no secondary at all, so such a visit fails on the score-completeness rule (`ERR_OBSERVATION_SCORES_INCOMPLETE`), keeping that error reachable rather than reusing `ERR_SECONDARY_OBSERVER_REQUIRED` (which the PRD defines only for the tier ≥ 4 direction).
4. **Errors the PRD leaves unnamed**: score before the window opens → `ERR_VISIT_STATE_INVALID`; SUSTAIN above the block-implied ceiling (non-`OBSERVER_RELIABILITY` grounds) → `ERR_BLOCK_GATE_NOT_MET`; ESCALATE of a non-escalatable field → `ERR_VALIDATION`; `OPEN_TRIAGE` against an unpublished cycle → `ERR_CYCLE_STATE_INVALID`.
5. **`ERR_OPEN_APPEAL_BLOCKS_ACTION` at filing is guarded but effectively unreachable** — filing drives the cycle to `UNDER_APPEAL`, so a second filing hits the cycle-state gate first. This is the PRD's own sentence order in §3.6 ("Filing is available while the cycle is in `AWARDED` or `ACTIVE`, only within 30 calendar days ..., and only when no appeal ... is already open"), so I kept the guard in PRD order rather than hoisting it.
6. **Observer certification** — `CERTIFY` requires `anchor_agreement_pct`, and additionally `certified_until` when the agreement reaches 85.00; below 85.00 the observer lands in `LAPSED` with `reliability_certified_until` cleared.
7. **`touch()` discipline on scores** — `ObservationScore` is a LEAN entity with no `version`, so cancel un-currents rows without touching them, and the visit is touched only when `(status, composite, reliability_pct, rescore_count)` actually changes.

### Step 6b — routes/funding.py + routes/coaching.py + routes/claims.py, subagent summary verbatim:

Done. All three route modules are written, compile cleanly, and the server boots with every route registered.

## Files written

| File | Lines | Endpoints |
|---|---|---|
| `.../workspace/implementation/routes/funding.py` | 327 | `POST /providers/<provider_id>/improvement-grants`, `GET /improvement-grants`, `GET /improvement-grants/<id>`, `POST /improvement-grants/<id>/accept`, `POST /improvement-grants/<id>/expenditures`, `GET /grant-expenditures`, `GET /grant-expenditures/<id>`, `POST /grant-expenditures/<id>/adjudicate`, `POST /improvement-grants/<id>/reimburse`, `POST /improvement-grants/<id>/close` |
| `.../routes/coaching.py` | 304 | `POST /providers/<provider_id>/coaching-allocations`, `GET /coaching-allocations`, `GET /coaching-allocations/<id>`, `POST /coaching-allocations/<id>/accept`, `POST /coaching-allocations/<id>/sessions`, `GET /coaching-sessions`, `GET /coaching-sessions/<id>`, `POST /coaching-sessions/<id>/complete`, `POST /coaching-sessions/<id>/cancel` |
| `.../routes/claims.py` | 176 | `POST /providers/<provider_id>/subsidy-claims`, `GET /subsidy-claims`, `GET /subsidy-claims/<id>`, `POST /subsidy-claims/<id>/adjudicate`, `POST /subsidy-claims/<id>/pay` |

No shared module was touched. House style from `cycles.py`/`providers.py` matched throughout (blueprint decls, `require(...)`, `lookups.get_*` / `own_*`, `store.base_record`/`touch`, `response.paginate(records, serializers.maker(kind))`, numbered-gate comments).

## Behaviour verified by an in-process smoke run
- Grant ledger identity `awarded == committed + reimbursed + available` held after offer → accept → 2 submissions → 2 approvals → reimburse → close.
- Category ceiling inclusive at exactly 400,000 (40 % of 1,000,000) and `ERR_GRANT_CATEGORY_CEILING_EXCEEDED` one cent above; `ERR_STALE_VERSION`/412 on bad `expected_grant_version`; `ERR_GRANT_NOT_OPEN` fires before the fiscal checks.
- Close computed `recovery_amount_cents = 125000` (PROF_DEV shortfall/2), drove `compliance_status → RECOVERY`, decremented `provider.reimbursement_adjustment_cents`, bumped provider version, and closed grant-funded allocations.
- Coaching: touching endpoints conflict (`ERR_ONSITE_CAPACITY_CONFLICT`), weekly `iso_week_key` bucket rejects only when strictly over the cap, period bounds → `ERR_SESSION_OUTSIDE_ALLOCATION_PERIOD`, wrong `coach_user_id` → `ERR_NOT_RESOURCE_OWNER` before period checks, hours ledger returned to `0 / 3.0 / 17.0` after a schedule-complete-cancel sequence.
- Claims: duplicate period, `ERR_CLAIM_MONTH_NOT_COVERED` on an uncovered month, INTERIM approval (multiplier 1.15, 73,600 ¢ round-then-sum), PAID → RECONCILE_REQUIRED → PAID with the adjustment returning to its pre-cascade value.

## Where PRD and SCAFFOLD appeared to diverge (PRD followed)

1. **Claim-submission ordering.** PRD §3.7 prose mentions the duplicate-period rule before "the provider must itself be ACTIVE", but the §2.7 ladder puts provider standing at step 11 and the business-constraint family (scaffold priority 53, `ERR_DUPLICATE_CLAIM_PERIOD`) strictly after it. I ordered provider-ACTIVE → duplicate, per the explicit ladder.
2. **`pay` precedence.** Scaffold lists `provider.status == ACTIVE` as an APPROVED→PAID precondition while PRD says a claim whose provider lost its rating "through … a withdrawal" is refused with `ERR_PROVIDER_UNRATED`. Payment is *not* in the §2.7 step-11 op list, so I check `ERR_PROVIDER_UNRATED` (null `current_tier`) **before** the ACTIVE check — the only ordering that makes both PRD sentences true.
3. **Reimburse has no declared state gate.** I added no status precondition (PRD names none), but skip the waterfall for `OFFERED`/`DECLINED` grants, which can hold no expenditure line at all — otherwise the helper's unconditional `available = awarded - committed - reimbursed` recompute would wrongly release the full award on a pre-acceptance grant.
4. **Role/decision mismatch on `/accept`** (Provider: ACCEPT/DECLINE/REMEDIATE; Admin: REOPEN) is unspecified; I raise `ERR_FORBIDDEN_ROLE` after body-schema validation. Unnamed grant-side cycle preconditions (funding cycle must be ACTIVE / not WITHDRAWN on ACCEPT and REOPEN) raise `ERR_CYCLE_STATE_INVALID`; REOPEN past the deadline raises `ERR_GRANT_SPEND_DEADLINE_PASSED`.
5. **`STATE_BASE` allocations** store `funding_grant_id` as `null` per PRD prose (a supplied value is still FK-resolved first, so a bogus id yields `ERR_FUNDING_NOT_FOUND`); `GRANT` source without `funding_grant_id` is `ERR_VALIDATION`.
6. **Completion tolerance** (`delivered_hours <= scheduled_hours + 0.5`) is treated as step-6 body range checking (`ERR_VALIDATION`), i.e. before the `ERR_SESSION_STATE_INVALID` state check.

## Boot check
`PORT=18873 python3 app.py` → `GET /improvement-grants` returns a healthy empty-page success envelope (`total_count: 0`, `has_more: false`); `/coaching-allocations` and `/subsidy-claims` both 200. No 404s, so all 24 routes registered.

### Step 6 — orchestrator verification

All 69 scaffold endpoints are now registered across 8 route modules (25 pre-existing + 44 new). `py_compile` clean over the whole implementation tree. No shared module was modified by either shard, so the two concurrent shards produced no conflicting edits.

## Step 5: Generate unit tests (completion of crashed run) — 2026-09-01T04:20:00.000Z

Run as five concurrent shards over the 92 design instances left untested by the crashed run. `test_helpers/` was already complete and was held read-only for all five shards, so no shard could clobber another's fixtures; each shard read only a pre-sliced design fragment under `/tmp/task2207_step5/`.

### Step 5a — test_11 / test_12 / test_13, subagent summary verbatim:

All three assigned files are written and compile cleanly. No file under `test_helpers/` or any other `test_suite/` file was touched.

## Files written

| File | Lines | Tests |
|---|---|---|
| `.../test_suite/test_11_combinatorial_formula.py` | 656 | 8 |
| `.../test_suite/test_12_non_linear_state_machine.py` | 758 | 11 |
| `.../test_suite/test_13_transitive_cascade.py` | 780 | 11 |

## Design tags (every test carries exactly one)

**test_11 — `combinatorial_formula` (3/3 instances, 8 tests)**
- `Design: Difficulty/combinatorial_formula/mode_a_nested_min_over_sequential_block_fold` — `test_block_two_shortfall_collapses_the_fold_and_caps_tier_five_points_at_tier_two`, `test_nested_min_award_derives_each_domain_point_entry_from_its_own_rule`, `test_tier_two_award_writes_the_twenty_four_month_validity_window`
- `Design: Difficulty/combinatorial_formula/mode_b_pinned_round_before_min_in_grant_waterfall` — `test_reimbursement_rounds_each_gross_to_whole_cents_before_the_three_way_minimum`, `test_reimbursed_total_is_the_sum_of_rounded_lines_and_never_re_rounded`, `test_tier_two_award_precedes_the_grant_offer_that_the_waterfall_settles`
- `Design: Difficulty/combinatorial_formula/mode_c_pinned_order_compliance_points_tier_then_tier_keyed_gate` — `test_award_recomputes_compliance_before_capping_staff_qualifications`, `test_compliance_floor_is_gated_on_the_awarded_tier_the_capped_run_produced`

**test_12 — `non_linear_state_machine` (4/4 instances, 11 tests)**
- `.../rating_cycle_awarded_under_appeal_awarded_cycle` — 2 tests
- `.../observation_visit_fork_join_with_reliability_rescore_loop` — 4 tests
- `.../improvement_grant_orthogonal_compliance_axis` — 3 tests
- `.../appeal_under_review_info_requested_bidirectional_rounds` — 2 tests

**test_13 — `transitive_cascade` (4/4 instances, 11 tests)**
- `.../appeal_sustain_tier_to_claim_to_provider_adjustment_chain` — `test_sustained_appeal_rewrites_the_tier_and_unpublishes_the_cycle`, `test_tier_change_flags_the_already_paid_claim_without_rewriting_its_money`, `test_flagged_claim_pushes_the_provider_adjustment_up_by_the_reconciled_difference`
- `.../cycle_expiry_four_hop_provider_allocation_grant_leaf_chain` — `test_expiry_run_past_the_inclusive_expiry_date_withdraws_the_cycle_and_unrates_the_provider`, `test_lost_tier_suspends_the_allocation_and_freezes_the_grant_before_its_deadline`, `test_expiry_cascade_reaches_the_leaves_returning_hours_and_committed_cents`, `test_expiry_cascade_moves_the_status_axis_only_and_leaves_the_cost_breakdown_intact`
- `.../provider_suspend_three_hop_publication_allocation_session_chain` — `test_suspension_suppresses_the_listing_suspends_the_allocation_and_cancels_the_session`, `test_reinstatement_reverses_the_first_two_hops_but_never_recreates_the_session`
- `.../grant_close_recovery_compliance_to_provider_adjustment_chain` — `test_close_prices_the_prof_dev_shortfall_and_drives_the_compliance_axis_to_recovery`, `test_close_leaves_the_waterfall_ledger_intact_and_closes_the_funded_allocation`

## Skipped instances

None. All 11 non-stub instances passed both filter conditions. One *sub-assertion* was dropped (not an instance): mode_c's `pct_before == 95.00` read of the provider before the award — PRD §4 describes `GET /providers/{id}` as returning "computed compliance", so whether the pre-award read shows the stale or recomputed figure is not uniquely derivable (condition b). The instance's actual point (recompute-before-cap → SQ 30→24, weighted 68.00 not 73.00) is asserted.

## PRD vs design disagreements

1. **Credential `fte` > 1 is illegal.** The design uses `fte` of 1.6/4.0/4.5/etc.; PRD §3.2 requires "greater than 0 and no greater than 1". Rewritten with `credential_specs(...)` splitting into ≤1.00 records that preserve the same qualifying total, so every compliance percentage is unchanged.
2. **mode_b `weighted_total == 45.42` is wrong.** The design omitted the `STAFF_QUALIFICATIONS` credential-fraction cap (compliance 65.00 → fraction 0.40 → cap 12, credited 14). PRD-derived value is **43.75**; asserted that. `awarded_tier == 2` unaffected.
3. **Design clock ordering breaks score entry.** Several instances set the clock to a date before `window_start`; PRD §3.4 admits the first score only at/after `window_start`. Fixed by using the spine's `scoring_clock = window_start` and moving `award_clock` later (effective dates unchanged).
4. **Design accepts grants against an only-`AWARDED` cycle.** PRD §3.8 requires the funding cycle to be `ACTIVE` and not `WITHDRAWN`. Spines are built to `ACTIVE`/`PUBLISHED` before the offer.
5. **`tool_code: ECERS_R`** is not a PRD enum member (only `ERS_INFANT_TODDLER`/`ERS_EARLY_CHILDHOOD`) — used `ERS_EARLY_CHILDHOOD`.
6. **`funding_source: STATE`** (instance I) is not a PRD enum member (only `GRANT`/`STATE_BASE`) — used `STATE_BASE`, which also matches the design's own asserted 500,000-cent state-base funding balance.
7. **Instance G's `+468720` needs §3.7 line 262 to disambiguate.** Read literally, §3.6 hop 3 prices the claim "under the reconciled variant", whose covering-cycle lookup excludes `AWARDED` cycles — which would give a *negative* adjustment. §3.7's "Appeal cascades push it up when a tier increase means past months were underpaid" pins the sign, so the reconciled total is computed at the new tier 5 (3,515,400 − 3,046,680 = 468,720). Both sentences are cited in the docstring.

All numeric literals (80.00, 50.00, 96.17, 43.75, 68.00, 2170000, 3046680, 3515400, 468720, 180000/16200/196200, 120000/10800/130800, 80000/7200/87200, 100000/180000/20000/280000/720000, 75000, 62778, validity/expiry timestamps) were recomputed with `decimal` + `ROUND_HALF_UP` against the PRD formulas and pasted as literals; no test reimplements a formula.

### Step 5b — test_14 … test_18, subagent summary verbatim:

All five files are written and compile clean.

## Files delivered

| File | Lines | Tests | Instances |
|---|---|---|---|
| `.../test_suite/test_14_validation_precedence.py` | 357 | 4 | 4/4 |
| `.../test_suite/test_15_boundary_precision.py` | 590 | 5 | 4/4 |
| `.../test_suite/test_16_cross_entity_state.py` | 474 | 3 | 3/3 |
| `.../test_suite/test_17_temporal_overlap.py` | 518 | 4 | 4/4 |
| `.../test_suite/test_18_compensating_invariant.py` | 482 | 3 | 3/3 |

`python3 -m py_compile` on all five: OK. No other file in `test_suite/` and nothing under `test_helpers/` was touched.

## Design tags (19 tests, all 18 instances, zero skips)

- `Difficulty/priority_pair_validation_conflict/` `award_by_forbidden_role_beats_cycle_state`, `path_not_found_beats_body_schema_on_visit_scheduling`, `observer_reliability_beats_schedule_conflict`, `grant_not_open_beats_funds_exhausted`
- `Difficulty/boundary_precision_check/` `reliability_pct_inclusive_at_exactly_83_33`, `weighted_total_exactly_at_tier_4_cutoff_and_compliance_floor` (2 tests: the 90.00 pass and the 89.00 fail on the identical 70.00 total), `coaching_hours_cap_inclusive_and_admin_fee_band_strict_less_than`, `grant_category_ceiling_floor_and_available_cents_zero_edge`
- `Difficulty/cross_entity_state_dependency/` `staff_credential_registry_state_gates_rating_cycle_award`, `open_appeal_state_gates_subsidy_claim_reconciliation_payment`, `observer_reliability_state_gates_observation_visit_finalization_and_scoring`
- `Difficulty/resource_temporal_overlap/` `observer_half_open_window_adjacency_across_providers`, `observer_same_provider_48h_cooldown_buffer`, `coaching_site_closed_interval_touching_endpoints`, `onsite_weekly_aggregate_capacity_bucket`
- `Difficulty/compensating_invariant/` `grant_funds_conserved_across_submit_then_reject`, `coaching_hours_conserved_across_schedule_then_cancel`, `subsidy_adjustment_conserved_across_interim_then_reconciled_pay`

**Instances skipped: none.** Every instance passed both the coverage and unique-derivability filters (after the repairs below).

## PRD vs design-fragment disagreements (all repaired in favour of the PRD, literals preserved)

1. **Role-auth error id**: PRD §2.1 says `ERR_ROLE_NOT_PERMITTED`/`ERR_MISSING_AUTH_HEADER`; §2.7's ladder and the §5 catalogue say `ERR_FORBIDDEN_ROLE`/`ERR_UNAUTHENTICATED`. Asserted `ERR_FORBIDDEN_ROLE` + 403 (two-of-three majority).
2. **`funding_source: STATE`** in the design → PRD allows only `GRANT`/`STATE_BASE`. Used `STATE_BASE`.
3. **`tool_code: ECERS_R`** → PRD allows only `ERS_INFANT_TODDLER`/`ERS_EARLY_CHILDHOOD`. Used `ERS_EARLY_CHILDHOOD`.
4. **Credential `fte: 4.0`** → PRD §3.2 caps `fte` at 1.00; split into 1.00-fte records via `credential_specs`.
5. **`weighted_total_exactly_at_tier_4_cutoff…` was internally impossible**: it wants `awarded_tier 4` from a single-observer visit, but PRD §3.5 check 1 refuses that with `ERR_SECONDARY_OBSERVER_REQUIRED`. Added a secondary observer with identical 5.0 scores (reliability 100.00); every boundary literal (70.00 / 90.00 / 89.00) is unchanged, and the instance's `reliability_pct is null` assertion was dropped.
6. **`observer_same_provider_48h_cooldown_buffer` was temporally incoherent** (2028 visit window scored at a 2026 clock; a RERATING cycle unopenable at that date). Rebuilt with visit 1 `[2026-08-30T09:00, 17:00)` → tier 1, validity 24 months, expires `2028-08-31T23:59:59.999Z`, then a **REMAND** cycle (§3.3 exempts REMAND from the re-rating window) so trigger 1 at `2026-09-01T08:00` (end + 39 h, geometrically disjoint) is a 409 and trigger 2 at `2026-09-01T17:00` (exactly end + 48 h, strict `<`) is a 201.
7. **`grant_funds_conserved_across_submit_then_reject` used a PROF_DEV line of 300,000 that lands exactly on the 30 % category ceiling.** Under PRD §3.8 the reimbursement waterfall starts each category's running total *at* `category_spend_cents`, which already includes that line's own amount, so the category room is 0 and `reimbursable_cents` would be 0 — contradicting the design's expected 300,000. The outcome is not uniquely derivable at the ceiling, so I moved the line to 100,000, where both readings agree (`reimbursable 100000`, `disallowed 0`). The conservation identity, the `category_spend_cents` restoration, the untouched reimbursed line and `compliance_status == UNDER_REVIEW` are all preserved: `0 + 100000 + 900000 == 1000000` after the reject, `250000 + 100000 + 650000 == 1000000` before it.
8. **`subsidy_adjustment_conserved…` never publishes the cycle**, yet PRD §3.7's coverage rule requires publication `PUBLISHED` for claim approval. Added a `publish_cycle` at clock `2026-09-20` (award 2026-08-25 + 10-day quiet period). All money literals verified: base 275,000; INTERIM 1.0500 → 102060 + 64638 + 145152 = 311,850; RECONCILED 1.0000 → 97200 + 61560 + 138240 = 297,000; parked delta exactly −14,850, returned to 0.
9. **Minor ambiguities left un-asserted rather than guessed**: whether a `LAPSE` decision clears `reliability_certified_until` (§3.4 states it only for the sub-85 `CERTIFY` path), and the intermediate visit status after a rescore (§3.4's "returns to `SCORES_ENTERED`" vs. the rescore-limit bound); in the latter case I assert the branch-revealing outcome (non-null `reliability_pct` on the FINALIZED visit and the cycle) instead.

All numeric literals were computed offline with `decimal`/`ROUND_HALF_UP` and pasted as literals; no test calls `round()`, `Decimal`, or re-implements a PRD formula. Tests were not run against a live server, per instruction.

### Step 5c — test_20 / test_21, subagent summary verbatim:

Both files are written, compile cleanly, and pass pyflakes.

## Files written

**`.../test_suite/test_20_corner_entities.py`** — 477 lines, 12 test functions, 12 `Design:` tags (one per instance, all from `entities`): `create_provider_returns_applied_with_echoed_inputs`, `provider_system_fields_are_server_minted_at_creation`, `provider_computed_fields_initialised_to_unrated_posture`, `provider_weekly_onsite_cap_hours_default_twelve`, `create_provider_missing_license_number_rejected`, `create_provider_region_code_outside_enum_rejected`, `staff_credential_level_above_six_rejected`, `get_provider_unknown_id_returns_provider_not_found`, `list_providers_pagination_reports_total_count_and_has_more`, `observation_score_is_append_only_with_no_version_field`, `self_assessment_under_unknown_cycle_returns_rating_artifact_not_found`, `rating_cycle_read_exposes_hybrid_cross_spine_links`.

**`.../test_suite/test_21_corner_state_machines.py`** — 858 lines, 12 test functions, 12 `Design:` tags (all from `state_machines`): `rating_cycle_starts_in_draft_and_unpublished`, `award_from_docs_verified_returns_cycle_state_invalid`, `second_enrollment_approve_on_enrolled_provider_rejected`, `sixth_lead_subscale_auto_advances_visit_to_scores_entered`, `single_observer_finalize_branch_nulls_reliability_pct`, `scores_on_finalized_visit_returns_visit_state_invalid`, `appeal_info_requested_loop_returns_to_under_review`, `appeal_deny_restores_cycle_active_and_republished_listing`, `dispute_escalate_then_reopen_triage_increments_round_only`, `provider_suspend_cascades_three_hops_to_coaching_sessions`, `expiry_run_cascades_four_hops_across_grants_and_coaching`, `grant_status_open_while_compliance_reaches_finding_issued`.

No files under `test_helpers/` were touched; no other file in `test_suite/` was created or modified.

## Skipped instances

**None.** All 24 instances (12 `entities` + 12 `state_machines`) passed both the coverage and unique-derivability filters — each is backed by a full quotable PRD sentence that pins one answer.

## Assertion-level drops (instance kept, individual claim dropped as PRD-silent)

Three assertions present in the design fragment were dropped rather than weakened, because no PRD sentence pins them:

1. `provider_system_fields_are_server_minted_at_creation` — design asserted `created_at == "2026-08-03T00:00:00Z"`. PRD §2.4 requires "exactly three fractional digits" and never says `created_at` reads the logical clock, so the literal is both malformed and underivable. Replaced with `assert_timestamp_format(created_at)` + `is_valid_uuid(id)`.
2. `award_from_docs_verified_returns_cycle_state_invalid` — design asserted `weighted_total == 0.00` at `DOCS_VERIFIED`. `weighted_total` is not in §3.3's begins-null list and its value at that stage is never stated. Dropped; the `domain_points` map (which §3.3 *does* pin as "provisionally recomputed") is asserted instead.
3. `dispute_escalate_then_reopen_triage_increments_round_only` — design asserted `published_snapshot.tier == 1`. PRD §3.6 says the snapshot contains "the awarded tier" without naming the key (`tier` vs `awarded_tier` not derivable). The four explicitly named snapshot keys (`weighted_total`, `domain_points`, `licensed_capacity`, `county_code`) are asserted instead.

## PRD-vs-design tensions noted

- **Timestamp format**: the design fragment consistently writes timestamp literals with no fractional digits (`2026-08-03T00:00:00Z`) while PRD §2.4 mandates three. All such assertions were converted to date-prefix or instant-prefix checks (`.startswith("2026-08-03")`, `.startswith("2026-08-06T09:00:00")`), never to the zero-fraction literal.
- **Award state gate ambiguity (PRD §3.5 line 216)**: "Issuing the award is an administrator action against a cycle sitting in `OBSERVATION_FINALIZED`" is immediately followed by "a provisional-variant award is meaningful only against a cycle still in `DOCS_VERIFIED`". Read strictly these conflict. The design instance triggers with `score_variant: FINAL`, which is rejected under *both* readings (the provisional sentence never licenses a `FINAL` award from `DOCS_VERIFIED`), so the test asserts `ERR_CYCLE_STATE_INVALID`/409 per §2.7's tenth step. A `PROVISIONAL` award from `DOCS_VERIFIED` would not have been uniquely derivable and was not tested.

## Computed literals (verified before pasting)

- Visit composite `5.75` = (5.5+6.0+6.5+5.0+6.0+5.5)/6 = 34.5/6, single rounding at end.
- Tier-1 `weighted_total` `26.00` = (12/20·0.30 + 8/20·0.20)·100.
- Tier-1 validity: award 2026-08-11 → `effective_date` 2026-09-01 → 24 months → `expires_on` `2028-08-31T23:59:59.999Z` → `rerating_window_opens_on` 2028-06-02 (used as the RERATING clock in the hybrid test), and 2028-09-01 chosen as the expiry-run clock since the boundary is inclusive.
- Coaching guards in the two cascade tests: base 10.0 h × 5,000 = 50,000 → 0.09 fee band → total 54,500 ≤ `spend_cap_cents` 500,000 (STATE_BASE binds below the tier-1 900,000 ceiling); 10.0 h ≤ tier-1 40.0 h ceiling; 3.0 session hours ≤ default `weekly_onsite_cap_hours` 12.
- Grant guards: EQUIPMENT 200,000 ≤ 40% × 1,000,000 category ceiling; both expenditure lines submitted *before* the first rejection, because §3.8 blocks submission and adjudication only at `FINDING_ISSUED` while `UNDER_REVIEW` still permits adjudicating the second line.

### Step 5d — test_22 / test_23, subagent summary verbatim:

Both assigned files are written, compile cleanly, and every emitted test carries exactly one verbatim-verified `Design:` tag.

## Files

| File | Lines | Test functions | Instances covered |
|---|---|---|---|
| `.../test_suite/test_22_corner_calculations.py` | 655 | 10 | 9 of 10 (`reliability_83_33...` expanded to 2 tests) |
| `.../test_suite/test_23_corner_validations.py` | 584 | 10 | 10 of 10 |

Verification run: `python3 -m py_compile` passes on both; a script checked that every `PRD §x.y: "…"` citation is a literal substring of `workspace/PRD.md` (0 mismatches), that tags == test count, and that no import is unused or missing. No test was run against a live server; nothing outside these two files was created or modified.

## Design tags emitted
calculations: `credential_compliance_filters_by_registry_status_and_level_floor`, `credential_compliance_expires_on_boundary_is_inclusive`, `credential_compliance_caps_at_one_hundred`, `composite_rounds_only_the_quotient_to_5_08`, `reliability_83_33_is_admissible_at_the_inclusive_boundary` (×2 — 83.33 passes, 66.67 rejected with `ERR_RELIABILITY_BELOW_THRESHOLD`), `weighted_total_exactly_seventy_awards_tier_four_and_36_months`, `block_folding_is_sequential_so_block_three_cannot_rescue_tier`, `admin_fee_band_boundary_makes_a_larger_base_cost_less`, `subsidy_interim_rounds_each_age_band_before_summing`.
validations: all ten (`p2`, `p3`, `p4`, `p6`, `p8`, `p9`, `p26`, `p60`, `p41`, `p42`), one test each.

## Skipped instance (1)
- **`calculations/waterfall_orders_by_invoice_date_and_rounds_each_line_first`** — fails condition (b), unique derivability. PRD §3.8 states the run's per-category running total "starts at that category's current `category_spend_cents` entry", and submission "adds it to that category's entry in `category_spend_cents`". In the design's scenario the categories are already committed to (or past) their ceilings, so PRD-literal category room is 0 / 49999 / 0 and `reimbursed_cents` is 49999 — not the design's 300000 / 150001 / 360000 and 810001. Asserting the PRD-literal numbers would erase the instance's distinguishing aspect (invoice-date ordering plus per-line rounding), so the instance is dropped entirely rather than weakened.

## PRD vs. design discrepancies found
1. **Waterfall double-counting (above).** The design assumes category running totals start at 0; the PRD says they start at `category_spend_cents`, which the submission path already incremented.
2. **`subsidy_interim_rounds_each_age_band_before_summing` arithmetic is wrong in the design.** It gives bands 44226 / 16001 / 8986 = 69213 and a 69212 counterfactual. Computed with `decimal`/`ROUND_HALF_UP`: TODDLER = 3 × 3800 × 1.30 × 1.08 = 16005.6 → **16006**, sum = **69218**, single-rounding counterfactual = **69217**. The test uses the computed literals.
3. **`p42` setup is illegal under the PRD.** The design schedules a coaching session for an `ENROLLED` provider, but §3.9 says "The provider must be `ACTIVE` for a session to be scheduled at all." The test uses a tier-1 `ACTIVE` provider (`weekly_onsite_cap_hours` 12, allocation 10.0 h, sessions in ISO week `2026-W38`), preserving the closed-interval touch at 12:00:00Z.
4. **`p26` block-starving mechanism differs.** The design claims compliance 50.00 caps `STAFF_QUALIFICATIONS` to 4 points; the PRD cap is `round(max_points × credential_fraction)` = 10 at 50.00 compliance, so that would not starve block 1. The test instead sets verified `STAFF_QUALIFICATIONS` to 5 against `block_min_points` 8 — block 1 is `NOT_CLEARED` regardless of the fraction rule, and the test proves it via a `FINAL` score preview before showing the award returns `ERR_CREDENTIAL_REGISTRY_UNLINKED`.
5. **PRD internal inconsistency (reported, not tested).** §2.1 names `ERR_MISSING_AUTH_HEADER` / `ERR_ROLE_NOT_PERMITTED`, while §2.7 and the §5 catalogue name `ERR_UNAUTHENTICATED` / `ERR_FORBIDDEN_ROLE`. The tests use the §2.7 + §5 catalogue names.
6. Minor: the design fragment writes `verified_on` / `expires_on` / `invoice_date` as full ISO timestamps; the tests use the plain date strings the PRD and `test_helpers` factories use.

All numeric literals (composite 5.08, reliability 83.33 / 66.67, weighted totals 70.00 and 84.00, validity dates 2029-08-31 / 2029-06-02 / 2028-08-31 / 2028-06-02, admin fees 5999 / 4500 and totals 55989 / 54500, subsidy 49300 → 69218, ceiling 400000 with 600000 remaining) were computed with `decimal` + `ROUND_HALF_UP` and pasted as constants; no test recomputes a formula.

### Step 5e — test_24 / test_25 / test_26, subagent summary verbatim:

Done. All three files written, compiled clean, and pyflakes-clean (no unused imports, no undefined names).

## Files delivered

| File | Lines | Test functions | Instances translated |
|---|---|---|---|
| `.../test_suite/test_24_corner_endpoints_errors.py` | 497 | 9 (one is `parametrize`d ×13) | 3 `endpoints` + 4 `errors` |
| `.../test_suite/test_25_corner_rbac.py` | 386 | 5 | 5 `rbac` |
| `.../test_suite/test_26_corner_cross_cutting.py` | 573 | 7 | 5 `cross_cutting_layers` + 2 `consistency_model` |

**19/19 instances emitted — zero skips.** Nothing else in `test_suite/` was created or modified; `test_helpers/` untouched; `workspace/implementation/` never read.

## `Design:` tags (one line per test, verbatim section/name)

test_24: `Corner/endpoints/score_preview_is_a_provisional_projection_that_persists_nothing`; `Corner/endpoints/visit_cancel_uncurrents_scores_and_frees_the_observer_interval`; `Corner/endpoints/publish_quiet_period_day_ten_inclusive_then_public_directory_shows_snapshot` (×2 functions); `Corner/errors/err_unauthenticated_when_only_family_viewer_may_omit_user_id`; `Corner/errors/not_found_families_are_distinct_per_resource_prefix` (×2: the 13-case parametrize on path params, plus the body-level `lead_observer_id` case); `Corner/errors/p47_claim_month_not_covered_beats_p58_zero_service_units`; `Corner/errors/err_grant_funds_exhausted_after_four_ceilings_consume_the_award`.

test_25: `Corner/rbac/peer_roles_cannot_enter_each_others_exclusive_operations`; `.../uninvolved_observer_blocked_then_named_observer_scores_and_cannot_finalize`; `.../coach_user_id_mismatch_blocks_session_write_before_period_checks`; `.../staff_credential_creation_is_shared_but_provider_cannot_registry_link`; `.../segregation_of_duties_blocks_the_awarder_and_any_unassigned_reviewer`.

test_26: `Corner/cross_cutting_layers/` `occ_expenditure_create_stale_grant_version_rejected_after_first_commit`, `credential_compliance_reconciles_after_create_link_and_expiry`, `provider_list_pagination_and_filter_stay_consistent_under_mutation`, `expiry_run_activates_the_award_only_on_the_effective_date`, `provisional_preview_and_final_award_diverge_on_the_same_cycle`; `Corner/consistency_model/` `create_response_and_immediate_read_agree_with_no_lag`, `verification_decision_is_visible_across_entities_in_the_same_response`.

## PRD vs. design-fragment disagreements (resolved in favour of the PRD)

1. **`ERR_MISSING_AUTH_HEADER` / `ERR_ROLE_NOT_PERMITTED` (PRD-internal).** §2.1 names those two identifiers, but neither appears in the §5 catalogue, which declares itself exhaustive ("carrying one of the identifiers below"). §2.7 and §5 both name `ERR_UNAUTHENTICATED` (401) and `ERR_FORBIDDEN_ROLE` (403). Tests assert the §2.7/§5 pair.
2. **Subsidy-claim setup was PRD-illegal.** The fragment's recipe for `p47_claim_month_not_covered_beats_p58_zero_service_units` submits a claim from an `ENROLLED` provider and expects 201, but §3.7 states "The provider must itself be `ACTIVE` to submit" (and §2.7 step 11 repeats it) — that setup would die on `ERR_PROVIDER_STATE_INVALID`. Rebuilt faithfully: an `ACTIVE` tier-1 provider claims service month `2026-08`, which precedes its validity window, so `rating_cycle_id` resolves null (§3.7) and approval fails `ERR_CLAIM_MONTH_NOT_COVERED` 422 before the all-zero child-days could reach `ERR_ZERO_SERVICE_UNITS`. Same precedence claim, legal preconditions.
3. **Coaching-session setup was PRD-illegal.** Same problem in `coach_user_id_mismatch_blocks_session_write_before_period_checks`: §3.9 says "The provider must be `ACTIVE` for a session to be scheduled at all", so the fragment's `ENROLLED` provider would return `ERR_PROVIDER_STATE_INVALID` rather than the intended 422. Rebuilt on an `ACTIVE` provider with an allocation period of 2026-09-01..2026-09-30 and an out-of-period session.
4. **Invalid `evidence_type` values in the fragment** (`SURVEY`, `PORTFOLIO`) — §3.3 permits only `POLICY`, `ROSTER`, `LESSON_PLAN`, `FAMILY_SURVEY`, `TRAINING_LOG`. Used `documentation_for()` throughout.
5. **Identities `admin_award_1` / `coach_1` / `coach_2`** do not exist in `TEST_USERS`; used `ADMIN_USER_ID` (the spine's actual awarder, asserted explicitly) and `COACH_USER_ID` / `COACH_ALT_USER_ID`.

## Assertions deliberately not made (would not have been uniquely derivable — noted rather than softened)

- `public_listing_visible` **after** a successful publish: §3.6 says publishing "sets the provider's `public_listing_visible` to true", but the very next sentence says the flag is true "exactly when the provider's `current_rating_cycle_id` is non-null and the cycle it names has publication state `PUBLISHED`" — and at day 10 the cycle is still `AWARDED`, so it is not yet current. The pre-publish `false` assertion is kept; the post-publish value is left unasserted.
- The tier key inside `published_snapshot`: §3.6 says the snapshot contains "the awarded tier" without naming the field, so the snapshot's `weighted_total` / `domain_points` / `licensed_capacity` / `county_code` (all named verbatim) are asserted and the tier key is not.
- `verified_on` / `expires_on` initial values on a new staff credential (§3.2 never states them) and the exact format of a self-assessment's `verified_on` (only its being stamped is stated).
- Which specific provider occupies offset 2 of the ENROLLED page: all four providers are created at one frozen clock instant, so `created_at` ties and the tie-break is unspecified; the test asserts page **partition** and set membership instead.

One judgement call worth flagging for the run-and-fix step: for the coach mismatch I assert `ERR_NOT_RESOURCE_OWNER` 403. §2.7's ownership step is scoped to "the two entity-backed roles" (Provider, Observer) and `Coach` is explicitly not entity-backed, so the identifier comes from elimination over the exhaustive §5 catalogue — `ERR_FORBIDDEN_ROLE` is excluded by its own definition (the `Coach` role *is* in the endpoint's permitted list) and `ERR_VALIDATION` is a body-schema code. It is the only fitting identifier, but it is derived rather than stated.

### Step 5 — orchestrator verification

```
COMPILE_OK (test_suite/ + test_helpers/ + implementation/)
test functions:            121
Design: tag lines:         121   (every test function tagged exactly once, 0 untagged)
distinct instances tagged:  94
total design instances:     95
DANGLING tags:            none   (every tag resolves to a real §1.8/§1.9 instance)
uncovered instances:         1   Corner/calculations/waterfall_orders_by_invoice_date_and_rounds_each_line_first
```

The single uncovered instance is Step 5d's documented unique-derivability skip, not an omission. Test-file numbering left no collisions with the pre-existing `test_10_dual_variant_scoring.py`, and no shard touched `test_helpers/`, so the five concurrent shards produced no conflicting edits.

## Step 7: Run tests and iterate — 2026-09-01T04:46:00.000Z

All 8 parallel rounds pass 133/133. Exiting.

## Summary

**Iterations run:** 2 (one fast single-round scouting run, then one full 8-round parallel sweep which came back clean — 133/133 in every round; note the suite actually contains 133 test functions, not 121).

First-round landscape: 127/133 passed. The 6 failures collapsed into 3 root causes, none of them a `build_rating_spine` / clock-ordering / role-header cluster — `test_helpers/` turned out to be PRD-faithful throughout and needed no changes.

**Tests deleted:** none. All 6 failures were partial-coverage cases handled under STEP 1c (offending assertion removed, rest of test kept).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_17_temporal_overlap.py` — `test_touching_observation_windows_are_legal_but_a_one_second_overlap_is_not`: removed the two assertions requiring the echoed `window_start` / `window_end` to be re-serialized as `...:00.000Z`. **COMPUTED-FIELD / format silence** — PRD §2.4 pins three fractional digits only for `created_at`/`updated_at` (and §3.5 for the server-computed `effective_date`/`expires_on`); it says nothing about normalizing a client-supplied instant on echo, so a faithful reader may echo the submitted string verbatim. *Design: Difficulty/resource_temporal_overlap/observer_half_open_window_adjacency_across_providers*
- `test_23_corner_validations.py` — `test_an_observer_window_may_touch_but_not_overlap_by_one_second`: same assertion, same reason. *Design: Corner/validations/p41_observer_half_open_touch_allowed_then_one_second_overlap_rejected*
- `test_18_compensating_invariant.py` — `test_a_submitted_then_rejected_expenditure_leaves_the_grant_ledger_identical`: removed the two `category_spend_cents["PROF_DEV"] == 100_000` assertions taken *after* a reimbursement waterfall run. **UNIQUE-DERIVABILITY collapse.** PRD §3.8 ends the waterfall with the bare clause "`category_spend_cents` is updated" without saying to what; it admits at least three faithful readings (set to the category running totals → 200 000; leave unchanged since the line's amount was already counted at submission → 100 000; swap amount for reimbursable → 100 000). The submit-side and reject-side `category_spend_cents` assertions are verbatim-covered and were kept. *Design: Difficulty/compensating_invariant/grant_funds_conserved_across_submit_then_reject*
- `test_21_corner_state_machines.py` — `test_expiry_run_cascades_four_hops_across_grants_and_coaching`: removed `category_spend_cents["EQUIPMENT"] == 0` after the freeze-void hop. **BRANCH-ASYMMETRIC SIDE EFFECT** — PRD renders the rejection branch fully ("`committed_cents` decreases…, `available_cents` increases…, and that category's `category_spend_cents` entry decreases…") but compresses the freeze/void branch to "returning each line's `amount_cents` to `available_cents` and reducing `committed_cents` by the same total", omitting the category tally. The `VOIDED` status, `committed_cents` and `available_cents` assertions are covered and were kept. *Design: Corner/state_machines/expiry_run_cascades_four_hops_across_grants_and_coaching*

**Fixes applied to `implementation/`:**
- `calculations.py`, `covering_cycle` / `tier_for_day` / `compute_tier_multiplier` / `compute_subsidy`: added an `admit_cycle_ids` pass-through so a named cycle counts as in force for the day-by-day tier lookup. Needed because hop 1 of the sustain cascade parks the cycle in `AWARDED`, which §3.7 excludes from the covering-cycle set — so hop 3 was valuing the claim at the tier-1 unrated multiplier and *reducing* the provider's balance by 703 080, directly contradicting §3.7's "Appeal cascades push it up when a tier increase means past months were underpaid".
- `cascades.py`, `flag_paid_claims_for_reconciliation`: values the reconciled amount with the just-re-awarded cycle admitted (yielding the PRD-implied +468 720), and records the applied delta on the claim.
- `routes/claims.py`, `pay_claim`: the reconciled payment now reverses the exact delta the cascade recorded, so §2.10's conservation rule ("the subsequent reconciled payment returns it to its pre-cascade value") holds even if the cycle's covering state differs between flagging and repayment.

No PRD-required check was removed or weakened, no endpoint/field/side-effect was added without a verbatim PRD sentence behind it, and storage remains in-memory only.

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` report `total=133 passed=133 failed=0 errors=0 skipped=0`.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-01T04:57:00.000Z

Five edits landed on five lines. Done.

## Result

`PRD.md` 438 lines / 107,395 bytes → `PRD_FINALIZED.md` 438 lines / 109,586 bytes. Line delta 0 (+0.0%); byte delta +2,191 (+2.0%). Five paragraph-level revisions, no new sections.

## Changes

- **§2.4** — insert — pins that server-minted/computed instants use the three-fractional-digit rendering (enumerated), while any date or instant arriving in a request body (`window_start`/`window_end`, `spend_deadline`, `invoice_date`, `period_start`/`period_end`, `scheduled_start`/`scheduled_end`, credential `verified_on`/`expires_on`, `reliability_certified_until`) is stored and echoed verbatim, only its parsed value being used for comparisons — `validation.py:251-254` (`req_instant` returns the raw string), `serializers.py:66-76` (`_value` formats only `datetime`), `store.py:64-73` (`fmt_ts` passes strings through).
- **§3.6 (sustain cascade, hop 3)** — insert — the reconciliation valuation admits the cycle the appeal has just re-awarded even though hop 1 parked it in `AWARDED`; it competes for each day under the usual greatest-`effective_date` rule, and the delta computed this way is what the later reconciled payment reverses — `cascades.py:233-243`, `calculations.py:342-357`, `routes/claims.py:159-175`.
- **§3.7 (covering cycle)** — revise — the "`DRAFT` through `AWARDED` … excluded entirely" claim now carries the single §3.6 exception, so the two paragraphs no longer contradict — `calculations.py:356`.
- **§3.8 (freeze/void)** — insert — voiding leaves `category_spend_cents` exactly as it stood (unlike rejection), so a voided amount stays counted against its category ceiling — `cascades.py:127-138`.
- **§3.8 (reimbursement waterfall)** — revise — the bare "`category_spend_cents` is updated" now reads that each of the four categories carries its own running total as the run left it (starting entry plus `reimbursable_cents` credited during the run) — `calculations.py:435-457`.

## Pre-edit search log

**Edit 1 — subject: rendering of date/instant fields on read.**
(b) Enumerated: `store.fmt_ts`; `serializers._value`/`dump`; `validation.parse_instant`/`req_instant`/`opt_instant`/`as_date`/`as_dt`; every `req_instant`/`opt_instant` callsite (`providers.py:233-243`, `coaching.py:64-65,164-165`, `funding.py:57,175`, `observation.py:142,201-202`); every server-set instant assignment (grepped `*_on"] =`, `published_at`, `enrolled_on`, `opened_on`, `paid_on`, `finalized_on`, plus `calculations.compute_validity:314-333`); `system.py:20-25` (`to_iso8601` is parsed, never echoed).
(c) Split the two `verified_on`/`expires_on` name collisions (self-assessment/cycle vs. staff credential) into separate clauses after noticing the first draft's list would have implied the credential's client-supplied `expires_on` is normalised; also said "only their parsed value is used for comparisons" rather than claiming storage is a string, since `parse_instant` also accepts date-only forms and bare offsets.

**Edit 2 — subject: the sustain cascade's reconciled valuation / the covering-cycle set.**
(b) Enumerated every `covering_cycle`/`tier_for_day`/`compute_tier_multiplier`/`compute_subsidy` callsite: `claims.py:53` (submit — no admission), `claims.py:117` (approval — no admission), `claims.py:162` (reconciled payment — no admission), `cascades.py:233` (sustain cascade — sole admitting caller). Also read `remedy.py:204-228` (hop 1 sets `AWARDED` and reruns validity) and `cascades.flag_paid_claims_for_reconciliation` window filter.
(c) Scoped the exception to this cascade only and said the admitted cycle "competes … under the usual greatest-`effective_date` rule" rather than "supplies the tier", because `admit_cycle_ids` only widens the candidate set — the ordinary tie-break still decides. Kept the payment side described as reversing the recorded difference, matching `claims.py:168-174`, without asserting the payment recomputes `reimbursement_cents` under an admitted cycle (it does not).

**Edit 3 — subject: the §3.7 universal exclusion sentence.**
(b) Same enumeration as Edit 2 plus `COVERING_STATES` at `calculations.py:339`.
(c) Phrased as "the single exception being …" so it stays true for the three non-admitting callers.

**Edit 4 — subject: `category_spend_cents` under expenditure voiding.**
(b) Enumerated every writer of `category_spend_cents`: `funding.py:70` (offer → `{}`), `funding.py:124` (accept → four zeros), `funding.py:213-216` (submit → add), `funding.py:270-272` (reject → subtract), `calculations.py:457` (waterfall → rewrite); every `VOIDED` writer (`cascades.py:132`, sole path) and every `freeze_grant` caller (`cascades.py:203` via `expire_cycle`, `system.py:56` via expiry run); the ceiling reader `calculations.category_ceilings` + `funding.py:191-197`.
(c) None — wording confined to the void branch and to the ceiling consequence, both of which hold for the single void path and for the one ceiling comparison.

**Edit 5 — subject: post-waterfall `category_spend_cents`.**
(b) Same writer set as Edit 4, plus `calculations.run_reimbursement_waterfall:430-458` (running totals seeded from the current entries for all four `CATEGORY_SHARE` keys) and `compute_recovery:461-479` (reads line-level `reimbursable_cents`, not the map).
(c) Said "each of the four cost categories" only after confirming `cat_totals` is keyed by all four `CATEGORY_SHARE` members regardless of which keys the prior map held, and left the existing PRD sentence about ceilings being cumulative across runs untouched, since it is exactly what this rewrite produces.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-01T05:26:00.000Z

Exit summary.

**Files**
- Source `workspace/PRD_FINALIZED.md` — 438 lines, 109,600 chars.
- Output `workspace/PRD_COMPLETED.md` — 438 lines, 130,284 chars. Char delta **+20,684**. Line count unchanged: every change is an in-paragraph insert or revision; no new sections, no new paragraphs, no reordering.

**Counts** — 51 changed lines: **39 ambiguity-pins**, **12 mismatch-revisions**. §4 (69-endpoint table) and §5 (55 error ids + HTTP statuses) were verified line-by-line against `auth.py`'s `require(...)` calls and `errors.py`'s `ERROR_STATUS` and needed no change.

**Changes** (impl paths relative to `.../workspace/implementation/`)

- §2.1 RBAC — revise — mismatch — the two error identifiers named in prose were wrong; `ERR_MISSING_AUTH_HEADER`/`ERR_ROLE_NOT_PERMITTED` replaced by `ERR_UNAUTHENTICATED` (401)/`ERR_FORBIDDEN_ROLE` (403), the only pair impl emits; also pinned empty-string headers and out-of-set roles as 401 — auth.py:41-51
- §2.2 Response Structure — insert — ambiguity — `request_id` shape pinned as `req_` plus twenty uppercase-alphanumeric characters — store.py:77-79
- §2.2 Response Structure — insert — ambiguity — `_meta.api_request_timestamp` pinned as real wall-clock, the one instant the logical clock does not govern — store.py:82-84
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` are `ERR_VALIDATION`; empty-string parameter is treated as absent and defaults; filters are exact-match string comparisons yielding an empty page on no match — response.py:55-78
- §2.3 Pagination — insert — ambiguity — insertion order pinned as the `created_at` tie-break — store.py:109-110
- §2.4 Identity/Timestamps — insert — ambiguity — every family's representation is an exact allow-list; the private keys (`_seq`, `_publication_before_suspension`, reconciliation amounts) never appear — serializers.py:8-59
- §2.4 Versioning — revise — ambiguity — completed the list of provider-`version`-bumping operations (enrollment resolution, verification approval, cycle open/activate/expire, standing change, appeal denial/withdrawal, `LICENSED_CAPACITY`/`COUNTY_CODE` correction), pinned that closing a grant bumps even on zero recovery and that the expiry run's compliance refresh is conditional — store.py:100-107, routes/system.py:100-118, routes/funding.py:297-326
- §2.6 Not-Found Families — insert — ambiguity — undeclared paths answer 404 with `ERR_VALIDATION` (not one of the six codes), undeclared methods 405 with `ERR_VALIDATION`, trailing slash insignificant — app.py:18,37-43
- §2.7 Rejection Order — insert — ambiguity — `domain_points` body rules (omitted domain reads as zero, no extra keys, 0..ceiling); absent/empty/non-object body reads as `{}`; malformed JSON is `ERR_VALIDATION` at 422 — validation.py:50-120, app.py:37-43
- §3.1 Standard Domains — insert — ambiguity — a supplied read-only value is silently discarded; non-boolean `observation_linked` and non-integer `block_level` are `ERR_VALIDATION`; five-row completeness and weights-sum are not enforced at declaration; observation derivation beats the credential cap when a domain is both — routes/system.py:66-101
- §3.1 Enrollment — revise — mismatch — `enrolled_on` is a full instant, and the `APPLIED` state test runs *before* the license re-confirmation, the one place uniqueness yields to target-state in the §2.7 ladder — routes/providers.py:87-109
- §3.1 Standing — insert — ambiguity — `action` enum pinned (`SUSPEND`/`REINSTATE`/`WITHDRAW`); reinstatement and withdrawal preconditions refuse with `ERR_PROVIDER_STATE_INVALID`/409, the same code as a wrong-origin-state refusal — routes/providers.py:111-165
- §3.2 Credentials — insert — ambiguity — registry-link required fields; the three optional inputs apply only when supplied, so a move back to `UNLINKED`/`PENDING`/`EXPIRED` never clears stored dates, and `registry_status` places no restriction on the transition — routes/providers.py:227-253
- §3.2 Compliance — insert — ambiguity — the recompute trigger set completed, and the compliance read pinned as the full provider representation plus `credential_compliance_pct`, `qualifying_fte`, `denominator_fte` — routes/providers.py:255-268
- §3.3 Cycle Open — revise — ambiguity — the three re-rating preconditions separated and pinned (no cycle at all vs. active cycle with non-null `rerating_window_opens_on` reached), all three failing with the same code — routes/cycles.py:59-131
- §3.3 Cycle Open — revise — ambiguity — `domain_points` and `block_clearance` pinned as empty objects at creation, alongside the null-field list — routes/cycles.py:100-130
- §3.3 Self-Assessment — revise — mismatch — check order corrected: body validation, then `DRAFT` state (`ERR_CYCLE_STATE_INVALID`), then the five-domain/weights identity (`ERR_VALIDATION`); evidence items keep first-appearance order — routes/cycles.py:182-231
- §3.3 Verification — insert — ambiguity — decision tokens `APPROVE`/`RETURN`, both refusals carrying `ERR_CYCLE_STATE_INVALID`/409 (no self-assessment state family) — routes/cycles.py:251-305
- §3.3 Score Preview — revise — ambiguity — `variant` is a query parameter defaulting to `PROVISIONAL` on absent/empty, `ERR_VALIDATION` otherwise; `FINAL` requires a `VERIFIED` self-assessment; persists nothing at all, not even recomputed compliance; returns the stored cycle with the variant's fields overlaid — routes/cycles.py:153-181
- §3.4 Observer Reliability — insert — ambiguity — decision tokens and their per-token field requirements (`CERTIFY` needs `anchor_agreement_pct`, `certified_until` required on that path), `LAPSE` leaves `reliability_certified_until` intact, `RETIRE` touches neither field, and no origin-state guard applies — routes/observation.py:134-171
- §3.4 Visit Scheduling — revise — ambiguity — empty/whitespace `secondary_observer_id` reads as absent (no self-collision, no `ERR_OBSERVER_NOT_FOUND`); both window bounds required and unordered at scheduling; both safety rules run after the `DOCS_VERIFIED` check — routes/observation.py:192-248
- §3.4 Score Submission — insert — ambiguity — admissible origin states pinned, pre-window submission refused with `ERR_VISIT_STATE_INVALID` (not a temporal code), and the visit's `updated_at`/`version` move only when status/composite/reliability/rescore actually change — routes/observation.py:290-365
- §3.4 Finalization Effects — insert — ambiguity — both branches recompute credential compliance before the final award, and neither writes any tier field onto the cycle — routes/observation.py:391-455
- §3.4 Finalization Gate — revise — mismatch — PRD required the visit to carry no `secondary_observer_id`; impl reaches `FINALIZED` from `SCORES_ENTERED` with a secondary whenever the secondary's six rows exist and reliability ≥ 83.33, and the tier ≤ 3 cap applies only to the genuinely single-observer case — routes/observation.py:391-455
- §3.5 Block Clearance — revise — ambiguity — `block_clearance` pinned as decimal-string keys (`"1"`,`"2"`,`"3"`), always all three present, values the two literal tokens — calculations.py:270-300
- §3.5 Award — insert — ambiguity — `score_variant` required and one of two tokens; the origin-state test precedes the variant test, so a wrong-state cycle is `ERR_CYCLE_STATE_INVALID` whichever variant was sent — routes/cycles.py:307-392
- §3.5 Expiry Hops — revise — mismatch — the provider's `current_rating_cycle_id`/`current_tier` are nulled only when the pointer still names the expiring cycle, while `public_listing_visible` is cleared unconditionally — cascades.py:187-203
- §3.5 Expiry Run — revise — mismatch — four fixed phases in `created_at` order; a grant freezes on passed `spend_deadline` **or** a funding cycle no longer `ACTIVE` (including unresolvable); compliance refresh bumps only changed providers; the run answers HTTP 200 with `data: {}` and no summary — routes/system.py:29-64
- §3.6 Publication — insert — ambiguity — no origin cycle-status gate; the sole precondition is non-null `awarded_on`, refused with `ERR_CYCLE_STATE_INVALID` first; the snapshot holds exactly five keys — routes/cycles.py:393-423
- §3.6 Public Ratings — revise — mismatch — returns the full rating-cycle representation, not a reduced snapshot view; `county_code` matches the snapshot while `tier` matches the live `awarded_tier`; non-integer `tier` is `ERR_VALIDATION`; empty filters ignored; no per-caller narrowing — routes/cycles.py:424-440
- §3.6 Appeal Filing — insert — ambiguity — required non-empty grounds; a null-`awarded_on` cycle is refused on the window code rather than a state code; the three tests run in a fixed order — routes/remedy.py:75-119
- §3.6 Appeal Review — revise — ambiguity — action enum pinned; both segregation-of-duties tests apply to all four actions and are evaluated before the body is read, so they precede the enum check; provider-side actions live on a separate endpoint and the narrative append/replace rule pinned — routes/remedy.py:139-203, 231-263
- §3.6 Sustain — insert — ambiguity — the four sustain tests in order, split across two codes (`ERR_VALIDATION` for absent/unchanged tier, `ERR_BLOCK_GATE_NOT_MET` for over-ceiling), null `highest_block_cleared` reading as zero — routes/remedy.py:204-230
- §3.6 Restoration — insert — ambiguity — `public_listing_visible` is recomputed from the standing rule rather than forced true, and the provider's `version` moves on both restorations regardless — cascades.py:53-60, routes/remedy.py:36-45
- §3.6 Dispute Filing — insert — ambiguity — `claimed_value` required, string-or-number only (never boolean/object/array), non-empty after trim; guarded only by role and ownership; touches neither cycle nor provider — routes/remedy.py:265-299
- §3.6 Dispute Triage — revise — mismatch — the role split is `ERR_FORBIDDEN_ROLE` after the token is read; `OPEN_TRIAGE` is the single token for all three entries into `TRIAGE` with per-origin preconditions (publication check from `FILED` only, `triage_round < 3` from the other two) and always increments the round — routes/remedy.py:319-392
- §3.6 Correction — revise — mismatch — the latest qualifying sustained appeal in `created_at` order is the one linked; capacity/county writes happen only when a snapshot exists, with integer coercion of `LICENSED_CAPACITY`; a `DOMAIN_POINTS` correction takes neither branch — routes/remedy.py:47-74, 394-418
- §3.7 Claim Submission — revise — mismatch — the §2.7 step-11 standing test deliberately runs *before* the step-9 uniqueness test, so a non-`ACTIVE` provider gets `ERR_PROVIDER_STATE_INVALID` rather than the duplicate code; unknown `child_days` band keys are `ERR_VALIDATION` while omitted bands default to zero; pricing fields all null at submission — routes/claims.py:35-67
- §3.7 Adjudication — insert — ambiguity — decision enum, per-branch origin states with `ERR_CLAIM_STATE_INVALID`, and rejection leaving multiplier/variant untouched and applying none of the three approval checks — routes/claims.py:89-132
- §3.7 Payment — revise — mismatch — guard order and scope corrected: `ERR_ZERO_SERVICE_UNITS` on the `APPROVED` origin only, then `ERR_PROVIDER_UNRATED` on **both** origins (PRD scoped it to reconciliation alone), then `ERR_PROVIDER_STATE_INVALID`, then the open-appeal test on `RECONCILE_REQUIRED` only — routes/claims.py:135-180
- §3.8 Grant Offer — insert — ambiguity — `spend_deadline` is a full timestamp read for its date; no provider-standing gate and no cycle status/ownership check at offer time; `category_spend_cents` starts genuinely empty, the four keys appearing only on acceptance — routes/funding.py:50-78
- §3.8 Grant Decisions — insert — ambiguity — decision enum; role-decision mismatch is `ERR_FORBIDDEN_ROLE`; every origin-state refusal carries the single code `ERR_GRANT_NOT_OPEN` and is evaluated first; remediation reads the compliance dimension alone with no disbursement gate — routes/funding.py:98-166
- §3.8 Expenditure Adjudication — insert — ambiguity — decision enum, and the `SUBMITTED` state test precedes the compliance hold — routes/funding.py:242-283
- §3.8 Reimbursement — insert — ambiguity — no disbursement-state guard (`OPEN`/`FROZEN`/`CLOSED` all run the waterfall); `OFFERED`/`DECLINED` answer 200 with only a `version` bump rather than an error — routes/funding.py:284-296
- §3.8 Grant Close — insert — ambiguity — `OPEN` required (`ERR_GRANT_NOT_OPEN`) and the state test precedes the unadjudicated-line sweep (`ERR_EXPENDITURE_STATE_INVALID`) — routes/funding.py:297-326
- §3.8 Recovery — revise — mismatch — `compliance_status` is set straight to `RECOVERY` from `NONE`/`MONITORING`/`FINDING_ISSUED`/`REMEDIATED` in one step (no observable intermediate); `recovery_amount_cents` is always written including zero; a zero recovery leaves the compliance dimension and the correction balance untouched, but `version` still moves — routes/funding.py:297-326, calculations.py compute_recovery
- §3.9 Allocation Create — insert — ambiguity — period bounds are timestamps compared by calendar date and unordered at creation; `funding_grant_id` mandatory in substance for `GRANT` (`ERR_VALIDATION`, checked last) but resolved-then-discarded for `STATE_BASE`; the grant need not share the provider or be `OPEN`, and provider standing is unexamined — routes/coaching.py:56-112
- §3.9 Acceptance — revise — ambiguity — wrong allocation state is `ERR_ALLOCATION_STATE_INVALID` and that test precedes the funding-grant test; provider standing unexamined — routes/coaching.py:133-155
- §3.9 Session Scheduling — revise — ambiguity — two standing gates in order: allocation `ACTIVE` (`ERR_ALLOCATION_STATE_INVALID`), then provider `ACTIVE` (`ERR_PROVIDER_STATE_INVALID`) — routes/coaching.py:156-233
- §3.9 Session Scheduling — insert — ambiguity — period containment is tested at date granularity (times of day never consulted), and the new session stores `delivered_hours` as null, not zero — routes/coaching.py:156-233
- §3.9 Session Completion — revise — ambiguity — `delivered_hours` required at one decimal place, and the tolerance breach (`ERR_VALIDATION`) is evaluated *before* the session's own state, so a terminal session re-completed with an impossible figure answers on the validation code rather than `ERR_SESSION_STATE_INVALID` — routes/coaching.py:253-303

Two self-corrections worth flagging: the expiry-run response is HTTP 200 with `data: {}` (`response.py:31-32`, `def empty(): return ok({}, 200)`), not 204; and appeal decisions bump the provider's `version` only on the deny/withdraw paths and on a sustained appeal that flags a PAID claim (`routes/remedy.py:204-230`), which is how the §2.4 list is now worded.

Orchestrator verification: no file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the green 8-round sweep, so `results.{1..8}.json` (133/133 each) remain valid for the delivered code. Pipeline complete through Step 9.
