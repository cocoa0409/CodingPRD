# Worklog — task_1751_iacuc_vivarium_management

## Step 1: Create task directory — 2026-08-14T13:21:00.000Z

Directory `tasks/task_1751_iacuc_vivarium_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate scaffold — 2026-08-14T13:57:43.787Z

All three artifacts are generated, lint-clean, and cross-verified. Here is the verbatim summary of what was generated for `/home/ubuntu/github/CodingPRD/tasks/task_1751_iacuc_vivarium_management/`:

**Files written**
- `SCAFFOLD.yaml` (2114 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1408 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1881 lines) — single top-level key `scaffold_corner_design`

**§1.0–§1.7 surface counts**
- **Entities: 17** — Investigator, Grant, Personnel, TrainingEnrollment, OccHealthEnrollment, Protocol, ProtocolReviewer, Cage, Animal, Litter, CensusRecord, BillingRun, PerDiemCharge, FacilityInspection, AdverseEventReport, ProtocolDeviation, ProcedureRoomBooking
- **State machines: 11** — Protocol (cyclic revision loop DRAFT↔review plus SUSPENDED↔APPROVED and terminal EXPIRED/WITHDRAWN), Cage (EMPTY/OCCUPIED/OVER_CAPACITY/DECOMMISSIONED with system flips), Litter, TrainingEnrollment, OccHealthEnrollment, BillingRun (branching DRAFT→{PROVISIONAL→FINALIZED→POSTED, VOIDED} with divergent per-branch side effects), AdverseEventReport, ProtocolDeviation, Animal, ProcedureRoomBooking, FacilityInspection
- **Concurrency rules: 2** (OCC on BillingRun.version for finalize; OCC on Protocol.version for suspend)
- **Calculations: 9** — per_diem_billing (PROVISIONAL vs FINAL dual variant, tiered rat max-rate, pinned per-day-round-then-sum order), cage_capacity (21-day pup-exemption threshold), census_reconciliation, breeding_productivity (weighted scoring), inspection_scheduling (180-day chronological lapse), training_gate, occ_health_gate, room_booking_conflict (30-minute turnover buffer, half-open), protocol_animal_cap (>= boundary)
- **Validations: 24** ordered priority rows (auth → schema → existence → state/OCC → safety incl. segregation-of-duties → constraint → temporal → referential → fiscal → uniqueness)
- **Endpoints: 76** including the `POST /iacuc/_clock/set_current_utc` test-driving clock with pinned default `2026-08-01T00:00:00Z`, full FK reverse-reachability GETs, and OCC-guarded finalize/suspend taking `expected_*_version`
- **Error catalog: 24** codes, every one anchored to at least one validation row or transition
- **Roles: 8** — IacucAdministrator, Investigator (entity_backed:Investigator), AnimalCareStaff (entity_backed:Personnel), AttendingVeterinarian (entity_backed:Personnel), FacilityManager, BillingCoordinator, TrainingCoordinator, OccHealthNurse; segregation-of-duties enforced (PI cannot review own protocol; reporter cannot close own deviation)

**§1.8 instances: 18** — exactly 2 per rule × 9 rules: dual_variant_calc (per-diem PROVISIONAL 2625 vs FINAL 1250 on billing; training-gate expiry flip on Personnel), combinatorial_formula (mode (a) rat max-tier mixed-age 4410 vs 3150; mode (b) pinned per-day rounding 840), non_linear_state_machine (Protocol revision cycle; BillingRun branching void paths), transitive_cascade (depth-3 deviation→protocol→cages+adverse-events; depth-2 adverse-event→auto-filed deviation), priority_pair_validation_conflict (state-vs-fiscal on submit; safety-vs-constraint on animal add), boundary_precision_check (animal cap at exact max; wean at exactly born_on+21d vs one second early), cross_entity_state_dependency (Protocol→Animal/Cage; CensusRecord→BillingRun), resource_temporal_overlap (room buffer half-open 10:15 rejected / 10:30 allowed; adjacent billing periods exclusive-end 21+10=31 days), compensating_invariant (grant budget conservation 500000→497375 across post+void; cage population conservation across transfer/retire)

**§1.9 instances: 41** across all nine claim-extraction sections (entities 8, state_machines 8, calculations 5, validations 6, endpoints 4, errors 2, roles 4, complexity_layers 3, consistency_model 1) — covering FCR quorum/veto tallies, pup-cap day-22 flip, 180-day inspection lapse at exactly one second past due, 72-hour adverse-event resolution deadline, OCC stale-version on both guarded endpoints, RBAC denials, ownership enforcement, pagination envelope, and immediate-consistency debit visibility.

**Verification**: `scaffold_lint.py` verdict pasted verbatim — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (561 calls scanned). Additionally verified by script: all `${var}` placeholders bound by earlier captures in-instance, all 59 instance names unique across both files, all grounds refs resolve to declared §1.1–§1.7 elements, no forbidden concurrency vocabulary, and enum closure (added `transfer-out` endpoint so `TRANSFERRED_OUT` is producible). No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-08-14T13:58:22.129Z

Copied `./INSTRUCTION.md` to `tasks/task_1751_iacuc_vivarium_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T14:14:31.307Z

All three hard contracts pass. The generation is complete and verified.

---

## Summary Report

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1751_iacuc_vivarium_management/workspace/PRD.md` — **333 lines**

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block, byte-identical — verified by containment check) · 2.3 Pagination · 2.4 The Logical Clock and Time-Driven Transitions · 2.5 Common Resource Properties · 2.6 Nested Resource Retrieval · 2.7 Optimistic Concurrency Control · 2.8 Validation Pipeline and Priority Order · 2.9 Monetary Precision and Rounding Conventions · 2.10 Segregation of Duties · 2.11 Hierarchical Consistency and Cascading Effects
- §3 Business Logic & Workflows: 3.1 Registering the Program · 3.2 Training and Occupational Health Clearance · 3.3 Protocol Authoring, Submission, and Committee Review · 3.4 Housing Operations: Cages, Animals, and Capacity · 3.5 Breeding Colonies and Litters · 3.6 The Daily Census · 3.7 Per-Diem Billing and Grant Posting · 3.8 Adverse Events, Deviations, and Protocol Suspension · 3.9 Facility Inspections and Procedure-Room Scheduling
- §4 Endpoint Definitions (76 rows, 4 columns — matches scaffold endpoint count exactly)
- §5 Error Code Catalogue (24 rows, 2 columns — matches scaffold error count exactly)

**Zero-Silence Rule coverage audit (mechanically verified):**

```
Contract 1 — Field-name coverage:
- 84 required names (all entities[].fields + endpoint inputs/params incl. to_iso8601, current_utc,
  decisions, expected_protocol_version, expected_billing_run_version, target_cage_id, target_cage_ids,
  and productivity outputs score/weaned_litters/weaned_pups/nonproductive_days): 84 present, 0 missing
- All 74 enum/state literal values present as exact strings
Status: PASS

Contract 2 — Rule coverage:
- validations[] priority: full 24-step global pipeline expressed as an ordered list in §2.8, with
  observable-ordering examples (cap-before-approval, mismatch-before-capacity, training-before-booking checks)
- concurrency_rules[]: 2/2 expressed — billing finalize (expected_billing_run_version, ERR_STALE_VERSION/412)
  and protocol suspend (expected_protocol_version, ERR_STALE_VERSION/412), each naming the guarded write,
  the OCC field, and the exact error; both restated in §3.7/§3.8 workflow prose
- state_machines: all 12 machines, all transitions expressed with preconditions + side effects, including
  DMR/FCR sibling branches at equal density, both euthanasia sources, both escalate sources, both void sources
- calculations: 9/9 in precise prose — per-diem dual variants (125/400/40 flat; rat tiers 75/150/210 with
  <21d and >365d boundaries; highest-tier-per-day mixed-age rule; per-day round-half-up then sum; FINAL
  excludes RETIRED/EUTHANIZED from status-change date), cage capacity (nursing exemption through day 21,
  counts day 22; suspension forces OVER_CAPACITY), census reconciliation, productivity score (3/0.5/0.05
  weights, floor at zero, 2dp half-up), 180-day inspection cycle (first cycle free, inclusive boundary),
  training gate (4 courses, unexpired COMPLETED), occ-health gate, 30-minute booking buffer (exact-30
  permitted), inclusive animal cap
- validations[] conditions: 24/24 matchable to error_ids in §2.8/§3 prose; applies_to scopes enumerated
  exactly (training gate → 3 operations; protocol-approved → 3 operations; capacity → 3 operations;
  cage mismatch → 2 operations; segregation → 2 operations; all singletons named at their workflow site)
- endpoints[].side_effects: expressed (grant budget init, reviewer row creation, version bumps, cascade
  details, provisional-charge deletion on void, conflict-set removal on cancel)
- sibling-branch symmetry: 6 parallel groups checked, equal density
Status: PASS

Contract 3 — §3 path purity:
- 435 backtick tokens scanned in §3; tokens starting with `/`: 0; bare HTTP-method tokens: 0;
  method+path tokens: 0 (endpoints named via state-transition framing, role+verb, capability description)
Status: PASS
```

**Scaffold ambiguities adjudicated:**
1. **`hold_reason` contradiction** — the `BillingRun.hold_reason` field description says "stored on run while PROVISIONAL," but the DRAFT→PROVISIONAL transition says the run *stays DRAFT* with `hold_reason` set when a census discrepancy blocks computation. I followed the state-machine text (the rule-bearing entry): rejection with `ERR_CENSUS_DISCREPANCY`, reason recorded in `hold_reason`, run remains `DRAFT`.
2. **`ERR_NOT_OWNER` scope** — applies_to mentions "animal create by investigator contexts" although RBAC assigns animal creation to `AnimalCareStaff`. Rendered generically (ownership-checked operations compare the owner FK; protocol submission named explicitly) without inventing an investigator animal-create flow.
3. **Clock side-effect list** — the clock endpoint's parenthetical omits occ-health expiry, but the `OccHealthEnrollment` machine defines clock-driven `CLEARED → EXPIRED`. Stated as "every time-based transition," including clearance expiry (state-machine-backed), with room bookings explicitly unchanged.
4. **Personnel-attach status code** — scaffold declares 201 for what resembles a modification; followed the scaffold and covered it in the §4 preamble's 201 enumeration.
5. **`capacity_adults` policy numbers** (mice 5, rats 2, rabbits 1, zebrafish 20) exist only in a field description; rendered as institutional-policy context in §3.4, not as a hard validation.
6. **FCR "majority"** — expressed as a majority of the three `COMMITTEE_MEMBER` rows.
7. **Post-gate boundary** — `expires_on >= period_end` rendered inclusively ("on or after").

The withheld difficulty/corner design files were not opened or referenced at any point.

## Step 6: Generate implementation — 2026-08-14T14:56:22.838Z

All done. Final state verified: all modules byte-compile, no stray processes, `__pycache__` removed.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1751_iacuc_vivarium_management/workspace/implementation/`):

- `start.sh` — executable; guarded dependency install (`python3 -c "import flask"` check), `exec python3 app.py` in foreground
- `requirements.txt` — flask>=3.0
- `app.py` — entry point; binds `0.0.0.0:$PORT` (default 10000); envelope-wrapped handlers for ApiError, 400, 404, 405, and unexpected exceptions
- `db.py` — in-memory stores (all 16 entity dicts empty at boot, zero seeding), logical clock starting at exactly 2026-08-01T00:00:00Z, UUID ids, ISO-8601 3-fractional-digit `Z` serialization, `IACUC-YYYY-NNNN` minting
- `errors.py` — ApiError plus all 24 catalog error IDs with their HTTP statuses
- `envelope.py` — `meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, `data` wrapper, pagination `limit`/`offset`/`total_count`/`has_more` (defaults 10/0, bounds 1–100), created_at-ascending sort
- `validation.py` — `X-User-ID`/`X-User-Role` auth (8 roles), payload field validators
- `domain.py` — serializers, computed fields (budget_remaining, animals_used_count, training/occ-health gates), cage-capacity recompute, placement history, clock-driven transitions
- `routes_admin.py`, `routes_protocols.py`, `routes_vivarium.py`, `routes_billing.py`, `routes_compliance.py`

**Endpoint count**: 76 implemented and registered (verified via Flask `url_map`), matching the scaffold endpoint table exactly.

**State machines implemented**: Protocol (incl. submit auto-route to DMR_REVIEW/FCR_REVIEW with reviewer-row creation, vote-tally outcomes, OCC-guarded suspend with cage/adverse-event cascade, reinstate recount, clock expiry at +3 years), Cage (EMPTY/OCCUPIED/OVER_CAPACITY/DECOMMISSIONED with suspension force-over), Litter (NURSING→WEANED→CLOSED with pup reassignment), TrainingEnrollment and OccHealthEnrollment (completion/clearance with +365d expiry via clock), BillingRun (DRAFT→PROVISIONAL→FINALIZED→POSTED, VOIDED with provisional-charge deletion), Animal (retire/euthanize/transfer-out/cage-transfer), AdverseEventReport (72h deadline, clock auto-escalation, SEVERE/MORBUND auto-files SERIOUS deviation), ProtocolDeviation (REPORTED→UNDER_REVIEW→CLOSED/SUSPENSION_IMPOSED cascading to protocol suspension), ProcedureRoomBooking, FacilityInspection (inclusive due_by boundary, late-complete mutates to LAPSED + 422, clock lapse).

**Calculations implemented**: per_diem_billing (PROVISIONAL cage-day model ignoring mid-period retire/euthanize vs FINAL reconciled-census model excluding RETIRED/EUTHANIZED from status-change date; rat per-day max age-tier 75/150/210; flat 125/400/40; integer-cents half-up per day then summed), cage_capacity (21-day nursing-pup exemption), census_reconciliation (discrepancy hold blocks compute-provisional), breeding_productivity (3·litters + 0.5·pups − 0.05·nonproductive_days, floored at 0, 2dp half-up), inspection_scheduling (+180d from last completed of same kind, first cycle free), training_gate, occ_health_gate, room_booking_conflict (30-min turnover buffer, exactly-30m allowed), protocol_animal_cap (inclusive `>=` boundary). Validation pipeline follows the §2.8 priority order (auth → role → payload → existence → ownership → state → OCC → SoD → gates → cap → approved → … → uniqueness), confirmed by tests (e.g., cap-before-approved, mismatch-before-capacity, training-before-booking-window).

**Boot smoke test**: `bash start.sh` was launched fresh 5 times on ports 18751–18757; every boot came up empty (no seeded entities; any id 404s; default clock exactly `2026-08-01T00:00:00.000Z`), bound `0.0.0.0:$PORT`, and answered HTTP within ~2.5s. On a single fresh boot, three verification suites (~90 assertions) all passed: `ALL SMOKE TESTS PASSED`, `ALL EXTENDED TESTS PASSED`, `ALL CAP/TRANSFER/RBAC TESTS PASSED` — covering envelope shape, RBAC/401/403, DMR and FCR tallies (incl. resubmission reviewer reset), segregation of duties, OCC 412s, provisional-vs-final billing divergence (500 vs 250 cents on mid-period euthanasia), rat aged-tier 210 billing, grant insolvency 402, census-discrepancy hold with `hold_reason`, training/protocol clock expiry, 72h auto-escalation, inspection lapse, room-conflict buffer boundary, wean-age gating, and productivity scoring.

## Step 5: Generate unit tests — 2026-08-14T15:02:00.000Z

All checks pass. Generation complete — here is the verbatim summary.

## Test counts per queue

**Queue A — Difficulty (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18/18 instances translated, 36 tests (exactly 2 per instance)**
- dual_variant_calc: `per_diem_provisional_vs_final_on_cage_billing`, `training_gate_completed_vs_expired_on_personnel`
- combinatorial_formula: `rat_cage_tiered_daily_rate_mixed_ages`, `per_diem_per_day_rounding_order`
- non_linear_state_machine: `protocol_review_revision_cycle`, `billing_run_branching_void_paths`
- transitive_cascade: `deviation_to_protocol_to_cage_and_adverse_event`, `adverse_event_escalation_to_deviation`
- priority_pair_validation_conflict: `state_vs_business_fiscal_on_protocol_submit`, `business_safety_vs_business_constraint_on_animal_add`
- boundary_precision_check: `animal_cap_at_exact_max`, `wean_age_exact_21_day_boundary`
- cross_entity_state_dependency: `animal_add_gated_by_protocol_approved`, `billing_finalize_gated_by_census_clean`
- resource_temporal_overlap: `room_booking_turnover_buffer_half_open`, `billing_period_adjacency_exclusive_end`
- compensating_invariant: `grant_budget_debit_equals_posted_charges`, `cage_occupancy_conserved_across_transfer`

**Queue B — Corner (`SCAFFOLD_CORNER_DESIGN.yaml`): 40/41 non-stub instances translated, 40 tests (index contains 0 `excluded_because:` stubs)**

## Instances skipped, with reasons

- `Corner/calculations/breeding_productivity_weighted_score` — **SKIPPED (fails unique derivability).** The pinned outcome (`score == 10.00` via `nonproductive_days == 30`) depends on day-boundary conventions the PRD does not pin: PRD §3.5 defines nonproductive days only as "the days since the cage became `OCCUPIED` on which no litter in the cage stood `NURSING` or `WEANED`". Whether the wean/close day itself counts, and whether the evaluation day is included, is unresolved — faithful PRD-only readings yield 29/30/31 nonproductive days, i.e. scores of 10.05/10.00/9.95. Gap left as a gap; no weakened test emitted.

**Setup repairs applied (pinned assertions preserved verbatim):** (1) `per_diem_provisional_vs_final_on_cage_billing` — the recipe's structured calls retired the mouse at the default clock (08-01) while the natural-language setup says "retired effective 2026-08-11"; I inserted `set_clock(2026-08-11T00:00:00Z)` before the retire and filed the 21 daily census records the NL setup requires, so the PRD formula uniquely yields FINAL 10 days/1250 vs PROVISIONAL 21 days/2625. (2) `inspection_completion_after_due_by_lapses` — the recipe moved the logical clock past `due_by` before completing, which would trigger PRD §3.9's automatic clock-driven lapse and make the complete call's error ambiguous (`ERR_INVALID_STATE` vs `ERR_INSPECTION_LAPSED`); I kept the clock before `due_by` so the pinned `ERR_INSPECTION_LAPSED`/LAPSED outcome is uniquely derivable. (3) `stale_version_on_suspend` — added the deviation→impose-suspension→reinstate detour so PRD §3.8's direct-suspend precondition ("some deviation on that protocol already stands in `SUSPENSION_IMPOSED`") is satisfied and OCC is the only failing check. (4) `version_increments_on_every_mutation` / `investigator_create_returns_201_with_system_fields` — assert the exact +1 version chain only; the absolute start value (`version == 1`) is not stated in PRD §2.5, so that sub-assertion was dropped (test still emitted with PRD-derivable assertions).

## Helper files written (`test_helpers/`, all under `/home/ubuntu/github/CodingPRD/tasks/task_1751_iacuc_vivarium_management/`)

- `types.py` — 20 status/field enums + 20 entity TypedDicts (all entities carry §2.5 common fields)
- `constants.py` — per-diem rates (125/400/40, rat tiers 75/150/210), capacity policy, 21/180/30/72h/365d/3y thresholds, shared dates
- `api_errors.py` — 24 `ApiErrorId` values with HTTP map registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (73 methods) + singleton
- `factories.py` — payload factories with auto-unique sequences; `dmr_decision_payload` / `fcr_decision_payload` tally builders
- `assertions.py` — per-entity `assert_*` + `parse_instant` + `assert_grant_invariant`
- `test_users.py` — 8 role headers; `make_investigator_headers` (entity-backed, mandatory for ownership-gated calls), `make_staff_headers`, `make_vet_headers`, `make_admin_headers` (for the segregation-of-duties probe)
- `fixtures.py` — composite setups: `create_cleared_personnel` (4-course + occ-health chain), `create_draft_protocol`/`create_approved_protocol`/`create_fcr_protocol_in_review`, `setup_occupied_cage`, `setup_provisional_run`, `setup_posted_mouse_run`, `setup_dual_variant_billing`, `setup_rat_tier_billing`, `setup_flat_rate_billing`, `setup_suspended_protocol`, `setup_reinstated_protocol`, `setup_breeding_cage`, `setup_booking_scenario`
- `__init__.py` — barrel export (framework generics + all PRD-specific names)

## Test files written (`test_suite/`)

`conftest.py` + `test_01_protocol_review_and_versioning.py` (8), `test_02_protocol_submission_gates.py` (9), `test_03_cages_animals_and_caps.py` (7), `test_04_litters_and_census.py` (6), `test_05_personnel_clearance_and_access.py` (9), `test_06_per_diem_calculation.py` (8), `test_07_billing_run_lifecycle.py` (8), `test_08_adverse_deviation_suspension.py` (9), `test_09_rooms_and_inspections.py` (6), `test_10_entities_and_envelope.py` (8) — **76 tests total**.

## Stage 2 self-check (tag audit) result

- 76 tests collected by pytest with zero import/syntax errors.
- Every test docstring ends with exactly one `Design:` line; all 76 tags resolve to real instances in the source yamls (no untagged, no dual-tagged, no dangling tags).
- Coverage: every difficulty instance has exactly 2 tests; every non-stub corner instance has exactly 1 (except the single documented skip).
- PRD citation: strict verbatim check passes — every ≥8-word quoted fragment in every docstring (including ellipsis-split pieces) survives a literal whitespace-normalized grep of `workspace/PRD.md`.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings; pyflakes clean of real issues (unused-import warnings fixed).

## Step 7: Test/fix iteration loop — 2026-08-14T15:26:11.180Z

(Subagent-written iteration record, originally headed "Step 9" by mistake — retitled by the orchestrator; it is the Step 7 loop record.)

**Iteration 1 sweep**: 8/8 rounds identical, 25/76 passed, 51 failures — all deterministic, one root cause plus latent blockers.

**Root cause (test_helpers bug)**: `dmr_decision_payload`/`fcr_decision_payload` keyed decisions by `reviewer_kind`; the implementation (PRD-faithful: §3.3 binds decisions to reviewer *rows*, §2.6 validates body foreign keys, and §4 exposes reviewer ids via GET /protocols/{id}/reviewers) requires `reviewer_id`. Kind-keying cannot even address the three same-kind FCR rows. Fixed factories + `fixtures.record_dmr_decision` (new `record_fcr_decisions`) to resolve reviewer ids from the reviewers listing; updated test_01's two FCR tests, the wrong-kind tally test (now references a COMMITTEE_MEMBER row of another protocol — existence passes, tally fails per §3.3), and the segregation-of-duties test (well-formed tally so priority 8 surfaces).

**Latent fixes (blocked behind root cause)**:
- `fixtures.setup_provisional_run` default census: now files one clean census per day of the period so the FINAL reconciled-census model (§3.7 "a day counts only when a reconciled census ... confirms occupancy for that day") reproduces the 2625-cent provisional amount the posting tests pin. Same fix in test_02's `_drain_grant_via_posted_run` (`file_daily_census(21)`).
- test_04 `test_wean_reassigns_pups_to_target_cages`: moved wean to born_on+22 days — at exactly 21 days pups are exempt from effective occupancy, so "target cage OCCUPIED" was not uniquely derivable (§3.4 eff==0 → EMPTY vs "a cage holding animals reads OCCUPIED"); at day 22 pups count (eff=4 ≤ 5) and OCCUPIED holds under every reading.
- test_08 `test_resolve_after_72h_requires_escalation_first` → renamed `test_escalated_report_resolves_after_deadline_and_minor_files_no_deviation`: the pinned ERR_RESOLUTION_OVERDUE outcome is reachable only if clock-set does not auto-escalate UNDER_TREATMENT reports; PRD §2.4's clock-trigger list ("protocol expiry, training-enrollment expiry, occupational-health clearance expiry, and inspection lapse detection") omits adverse-event escalation while §3.8 says "the system also escalates an UNDER_TREATMENT report automatically when the 72-hour deadline is breached" — two faithful implementations diverge (unique-derivability collapse). Per partial-coverage handling, kept the derivable fragment: UNDER_TREATMENT→ESCALATED, ESCALATED→RESOLVED carries no deadline (verbatim §3.8), MINOR escalation files no deviation.

**Iteration 2 sweep**: 8/8 rounds, 76/76 passed each. No flakiness. Implementation untouched (no implementation bug found).


## Step 7 (orchestrator record): verbatim exit summary — 2026-08-14T15:26:11.180Z

## Summary — task_1751_iacuc_vivarium_management: CLEAN 8/8 sweep, 76/76 passing

**Iterations run:** 2 (iteration 1: 51 deterministic failures in all 8 rounds; iteration 2: 76/76 in all 8 rounds, zero flakiness).

**Tests deleted:** 0.

**Tests trimmed (unique-derivability collapse, per STEP 1c partial-coverage split):**
- `test_08::test_resolve_after_72h_requires_escalation_first` → renamed `test_escalated_report_resolves_after_deadline_and_minor_files_no_deviation`. The pinned `ERR_RESOLUTION_OVERDUE` outcome is reachable only if clock-set does not auto-escalate `UNDER_TREATMENT` reports. PRD §2.4 lists clock-triggered transitions as "protocol expiry, training-enrollment expiry, occupational-health clearance expiry, and inspection lapse detection" (adverse-event escalation absent), while §3.8 states "the system also escalates an `UNDER_TREATMENT` report automatically when the 72-hour deadline is breached" — two faithful implementations diverge (eager-on-clock-set makes the resolve-rejection sentence unreachable; manual-only makes the auto-escalation sentence dead). Kept the derivable fragment: `UNDER_TREATMENT→ESCALATED`, `ESCALATED→RESOLVED` carrying no deadline, and MINOR escalation filing no deviation (all verbatim §3.8). Feedback for generators: corner instance `adverse_event_resolve_overdue_requires_escalation` pins an outcome the PRD does not uniquely determine (state-vs-clock-trigger ambiguity).

**Fixes applied to `test_helpers/`:**
- `factories.py` — `dmr_decision_payload(reviewer_id, decision)` / `fcr_decision_payload(reviewer_ids, *decisions)`: decisions now bind reviewer rows by server-minted `reviewer_id` (was `reviewer_kind`, which cannot address the three same-kind FCR rows; PRD §3.3 + §2.6 FK-existence rule). Root cause of all 51 observed failures.
- `fixtures.py` — `record_dmr_decision` now lists the protocol's reviewers and references the `DESIGNATED_MEMBER` row by id; added `record_fcr_decisions` (zips decisions onto the three `COMMITTEE_MEMBER` rows); `setup_provisional_run` now files a clean census for every day of the period by default (PRD §3.7 FINAL model counts a day only when a discrepancy-0 census confirms it — the old single-day default made finalize yield 125 instead of the pinned 2625); added `_period_days` helper.

**Fixes applied to `test_suite/`:**
- `test_01_protocol_review_and_versioning.py` — two FCR tests now use `record_fcr_decisions`; `test_dmr_wrong_reviewer_kind_rejected` references a `COMMITTEE_MEMBER` reviewer row of a second (FCR) protocol (existence passes, tally fails → `ERR_INVALID_VOTE_TALLY`, faithful to §3.3 "exactly one decision for the single `DESIGNATED_MEMBER` row"); `test_investigator_cannot_record_review_on_own_protocol` sends a well-formed valid tally so segregation-of-duties (priority 8) is the surfaced failure.
- `test_02_protocol_submission_gates.py` — `_drain_grant_via_posted_run` files 21 daily clean census records so the FINAL charge really drains the 2625-cent grant.
- `test_04_litters_and_census.py` — `test_wean_reassigns_pups_to_target_cages` weans at born_on+22 days: at exactly 21 days pups are exempt from effective occupancy, so "target cage OCCUPIED" was underdetermined (§3.4 "whenever effective occupancy falls to zero the cage becomes `EMPTY`" vs "a cage holding animals reads `OCCUPIED`"); at day 22 pups count (eff=4 ≤ 5) and OCCUPIED holds under every reading.

**Fixes applied to `implementation/`:** none — no implementation bug found; every failure traced to test-artifact setup/payload issues, and the implementation's checks were PRD-faithful throughout.

## Step 8: Finalize PRD — 2026-08-14T15:36:00.000Z

PRD_FINALIZED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1751_iacuc_vivarium_management/workspace/PRD_FINALIZED.md` with exactly 3 inline edits, each tracing to a step_7_diff item.

## Size delta
- PRD.md: 333 lines / 45,743 bytes; PRD_FINALIZED.md: 333 lines / 46,392 bytes — 0% line delta, +1.42% byte delta (all edits are inline sentence-level revisions; no sections added).

## Changes (one bullet per edit)
- **§2.4 — revise** — added "the automatic escalation of `UNDER_TREATMENT` adverse-event reports whose 72-hour resolution deadline has been breached (§3.8)" to the clock-triggered transition list, resolving the §2.4-vs-§3.8 conflict in the implementation's favor (impl auto-escalates eagerly at clock-set) — `implementation/domain.py:368-374` (auto-escalation + SEVERE/MORBUND deviation cascade), sole caller `implementation/routes_admin.py:36-37`.
- **§3.3 — revise** — pinned the `decisions` payload wire format: a list of objects each carrying `reviewer_id` (server-minted reviewer-assignment row id, as exposed by the reviewer listing) and `decision` (`APPROVE`/`REQUIRE_MODIFICATIONS`/`WITHHOLD`), with unmatched `reviewer_id` rejected `ERR_NOT_FOUND` per §2.6 — `implementation/routes_protocols.py:163-188` (parse + global existence check), tally id-set matching at `routes_protocols.py:200-216`.
- **§3.4 — revise** — "whenever effective occupancy falls to zero the cage becomes `EMPTY`" gained ", even if nursing pups still exempt from the count are physically present in it", pinning the eff-based status rule the implementation exhibits (a day-21 wean target with only exempt pups reads EMPTY; OCCUPIED only once pups count on day 22) — `implementation/domain.py:129-155` (`recompute_cage`), `implementation/routes_vivarium.py:417-431` (wean recompute), `implementation/routes_protocols.py:308-317` (reinstate recount).

**Step-7 items verified as needing no edit:** the census-per-day fixture changes (`setup_provisional_run`, `_drain_grant_via_posted_run`) are pure test-setup bugs — §3.7 already pins "a day counts only when a reconciled census — a census record whose `discrepancy` is zero — confirms occupancy **for that day**" (per-day requirement explicit; impl `domain.py:202-212` additionally requiring `physical_count >= 1` is a fair reading of "confirms occupancy" and was left under-determined). The `test_01` SoD/valid-tally change exercised §2.8 priority ordering (SoD 8 before tally 15), already pinned verbatim.

## Per-edit pre-edit search log
1. **§2.4 edit** — (a) subject: the set of clock-triggered transitions. (b) enumerated: `routes_admin.py:30-38` (only `apply_clock_transitions` caller), `domain.py:346-377` (protocol expiry, training/occ-health expiry, inspection lapse at `t > due_by`, adverse-event auto-escalation at `t > reported_at+72h` incl. deviation cascade, cage recompute), `routes_compliance.py:218-233` (resolve guard retained), grep confirmed no booking logic in clock transitions. (c) adjustment: listed only the adverse-event item with a §3.8 cross-reference (so §3.8's cascade sentence covers the automatic case); deliberately did not add clock-driven cage recompute — it is a §2.11 reconciliation, no step-7 item traces to it.
2. **§3.3 edit** — (a) subject: review-decisions payload shape and reviewer-row existence. (b) enumerated: `routes_protocols.py:158-253` (sole `decisions` parser; `reviewer_id` with `id` fallback at line 170; global-store existence at 186-188; per-path id-set tally at 200-216), `_create_reviewers` (110-134), `list_reviewers` (256-262), `ser_protocol_reviewer` (`domain.py:468-476`); cross-checked test_01's foreign-row test (existence passes, tally fails → `ERR_INVALID_VOTE_TALLY`) and SoD test (priority 8 surfaces before 15). (c) adjustment: existence clause says "no reviewer assignment row" without scoping to the protocol (impl checks the global store), and the `id` alias was left unpinned (no test exercises it; under-determination preferred).
3. **§3.4 edit** — (a) subject: cage status when eff==0 with exempt pups physically present. (b) enumerated every cage-status path: `domain.py:129-155` `recompute_cage`, `domain.py:311-324` `suspend_protocol_cascade` (OCCUPIED-only; EMPTY cages untouched), `domain.py:376-377` clock recompute, `routes_protocols.py:308-317` reinstate, `routes_vivarium.py:201/250-252/268/285/302/346/427-431` (all animal/litter mutations) — all purely eff-based. (c) adjustment: scoped the clause to the pinned case ("even if nursing pups still exempt from the count are physically present") rather than a universal "status derives from effective occupancy alone" claim, avoiding tension with the following verbatim sentence "Placing the first animal into an `EMPTY` cage flips it to `OCCUPIED`" (adult-placement case); "otherwise a cage holding animals reads `OCCUPIED`" kept verbatim since eff ≥ 1 entails animals present.

## Step 9: PRD completeness scan — 2026-08-14T15:52:53.825Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1751_iacuc_vivarium_management/workspace/PRD_COMPLETED.md` is written — a pure in-place patch over `PRD_FINALIZED.md` (27 lines revised, no lines added/removed, no new sections).

## Summary

**Source vs output**: PRD_FINALIZED.md 333 lines / 46,392 chars → PRD_COMPLETED.md 333 lines / 51,351 chars (char-delta **+4,959**). All changes are inline paragraph inserts/revisions.

**Counts**: 34 ambiguity-pins, 5 mismatch-revisions (grouped into 27 edited paragraphs).

**Changes** (section — insert/revise — class — what — impl ref):

- §2.3 — insert — ambiguity — `created_at` ties broken by creation (insertion) order; invalid `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400; `has_more` ⟺ `offset`+`limit` < `total_count` — envelope.py:62-93, 34
- §2.4 — insert — ambiguity — clock set also recomputes every cage's occupancy (pups aging past 21d can flip to `OVER_CAPACITY`; version bumps only on status change) — domain.py:375-377
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — db.py:79-89
- §2.9 — revise — mismatch — scheduling datetimes compared at full timestamp precision, not "to the second" — routes_compliance.py:106,373; domain.py:365
- §3.3 — insert — ambiguity — `protocol_number`: YYYY = logical-clock year, NNNN = zero-padded per-year sequence from 0001 — db.py:59-64
- §3.3 — insert — ambiguity — server-assigned `reviewer_name`s (`Designated Member`, `Committee Member 1-3`); reviewer rows reused on resubmission — routes_protocols.py:110-134
- §3.3 — insert — ambiguity — decision objects accept `id` as alias for `reviewer_id` — routes_protocols.py:170
- §3.3 — insert — ambiguity — `expires_at` = three calendar years after approval; Feb 29 → Feb 28 — domain.py:36-41
- §3.3 — insert — ambiguity — attach personnel: no per-protocol ownership check; re-attaching same member succeeds (201), bumps version, no duplicate — routes_protocols.py:321-337
- §3.4 — revise — ambiguity — species capacity caps (5/2/1/20) are advisory policy, not enforced; any positive `capacity_adults` accepted — routes_vivarium.py:66
- §3.4 — insert — ambiguity — supplied `litter_id` validated for existence only — routes_vivarium.py:162-163
- §3.4 — revise — mismatch — suspension forces `OVER_CAPACITY` only on cages still holding animals; zero-occupancy cages stay `EMPTY` — domain.py:136-146, 317-320
- §3.4 — insert — ambiguity — transfer applies only consistency+capacity checks (no ceiling/approval re-check); same-cage transfer permitted, skips capacity — routes_vivarium.py:230-253
- §3.5 — insert — ambiguity — litter pups inherit cage species, get `PUP-`-prefixed server tags, alternate sex starting `M`; litter recording validates existence only (no cage-kind/approval/ceiling gates) — routes_vivarium.py:310-347
- §3.5 — revise — ambiguity — wean: only `ALIVE` pups moved, round-robin across listed targets; targets validated for existence+capacity only; `weaned_count` = full `pup_count` regardless — routes_vivarium.py:395-431
- §3.5 — insert — ambiguity — nonproductive days: inclusive day range from occupation day through today; day productive if a litter born before day's end and not closed before its start; `EMPTY` resets the occupation clock — domain.py:266-304, 149-152
- §3.6 — revise — mismatch — `census_date` stored as supplied (not forced to midnight), day-level comparisons use its UTC calendar day; `system_count` counts `ALIVE` animals at filing moment; decommissioned cage → `ERR_INVALID_STATE` 409; duplicate same-day censuses allowed — routes_vivarium.py:452-476
- §3.7 — insert — ambiguity — billing period instants stored as supplied; billable days = calendar day of `period_start` through day before calendar day of `period_end` — domain.py:225-227
- §3.7 — insert — ambiguity — occupancy reconstructed from placement intervals; retirement/euthanasia leave placements open (provisional bills through `period_end`), transfer/transfer-out/weaning close them; rat age evaluated at start of each billable day; charge `rate_cents` = highest daily rate applied — domain.py:162-199, 258; routes_vivarium.py:256-303
- §3.7 — revise — mismatch — FINAL model: reconciled census must also have `physical_count` ≥ 1; exclusion extended to `TRANSFERRED_OUT` animals — domain.py:183-212
- §3.7 — insert — ambiguity — finalization deletes provisional rows and mints new `FINAL` rows — routes_billing.py:161-168
- §3.7 — revise — mismatch — posting solvency evaluated per grant on the run's total charges to that grant (not per charge) — routes_billing.py:183-196
- §3.8 — insert — ambiguity — adverse-event `animal_id` validated for existence only (need not belong to protocol) — routes_compliance.py:133-135
- §3.8 — insert — ambiguity — auto-filed SERIOUS deviation names the event's reporter, carries system-generated description, begins `REPORTED` — domain.py:327-339
- §3.8 — insert — ambiguity — direct deviation filing allowed against a protocol in any state; impose-suspension cascade applies only when protocol stands `APPROVED` — routes_compliance.py:240-259, 327-331
- §3.8 — insert — ambiguity — direct suspend without a `SUSPENSION_IMPOSED` deviation → `ERR_INVALID_STATE` 409, surfaced before the version check; reinstate precondition failures → `ERR_INVALID_STATE` 409; frozen cages recounting to zero return to `EMPTY` — routes_protocols.py:265-318
- §3.9 — insert — ambiguity — inspection completion takes `completed_at` from the request; `deficiency_count` optional (omission keeps scheduled value) — routes_compliance.py:94-105
- §3.9 — insert — ambiguity — booking `end_at` must fall after `start_at` (else `ERR_INVALID_REQUEST` 400) — routes_compliance.py:349-350

Everything else in the implementation (RBAC tables, validation priority order, state machines, rate constants, OCC guards, SoD rules, cascade behavior, envelope shape, error catalogue) was already uniquely pinned by the PRD and left untouched.
