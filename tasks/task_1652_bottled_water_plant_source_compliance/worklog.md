# Worklog — task_1652_bottled_water_plant_source_compliance

## Step 1: Create Task Directory — 2026-08-14T04:55:00.000Z

Task directory `tasks/task_1652_bottled_water_plant_source_compliance/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-14T07:14:52.132Z

All three scaffold artifacts are generated and verified. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Deliverables (in `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/`)

**SCAFFOLD.yaml** — compliance_audit × quota_allocation archetype; 12 entities (Plant, WaterSourcePermit, WithdrawalEvent, TreatmentRun, LabTest, BottlingLine, PreformDelivery, ProductionLot, RecallEvent, ReturnableBottle, WashBatch, CommunityWaterReport), 72 endpoints, 40 error codes, 11 ordered validation priorities, 9 calculations, 10 state machines, 3 OCC concurrency rules, 6 opaque roles under a segregation-of-duties model (record-vs-validate and complete-vs-release bound by X-User-ID on shared endpoints). Clock endpoint carries the mandatory `2026-08-01T00:00:00Z` default; one `/_inject/bottle-wash-cycles` test-driving endpoint justifies the 150-cycle boundary.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, 2 per rule, each with fully structured `setup_api_calls`/`trigger` chains and precomputed literal asserts:
- dual_variant: permit provisional-vs-certified gallon aggregates; bottle gross-vs-sanitized pools (different domain, different variant shape)
- combinatorial: 5-input treatment verdict with SPRING/purified branch split (mode a); per-source-then-sum acre-feet rounding with pinned order (mode b) — the rounding pair (163088 gal + 1 gal → 0.500 vs sum-first 0.501) was numerically executed after an initial pair failed to diverge
- non-linear machines: bottle sanitation cycle with exactly-once counter; lot QA_HOLD↔REWORK loop
- cascades: SOURCE_RAW FAIL → permit SUSPENDED → SCHEDULED runs CANCELLED → posture BREACH; recall → lots RECALLED → bottles QUARANTINED → posture BREACH
- priority conflicts: state-vs-constraint (suspended permit beats cap), safety-vs-referential (sanitation-pending beats cross-plant)
- boundaries: exact daily-cap gallon; wash-cycle 149/150
- cross-entity gates: lot release ↔ run VALIDATED; report publish ↔ event finalization
- temporal overlap: half-open line windows (adjacency allowed) vs washer 30-minute purge buffer (adjacency rejected) — different semantics, different resources
- compensating invariants: preform reservation create/cancel (5000/0/5000 restored exactly); withdrawal record/void (provisional month 0 restored, version still advances)

**SCAFFOLD_CORNER_DESIGN.yaml** — 91 instances (77 live + 14 `excluded_because` stubs linked to §1.8) across all nine claim-guide sections, including the full report-supersede correction saga, overdue-grace 7/8-day boundary, 90% WATCH threshold, OCC stale-version progressions, RBAC denials, and a list/read surface sweep covering every remaining endpoint.

Cross-audits all pass: every grounds reference resolves, every catalog error is referenced and exercised, every endpoint appears in at least one chain, instance names unique across both design files, no forbidden concurrency vocabulary, enum closure complete, response envelope verbatim, and the scenario string stored verbatim as a single line.

## Step 3: Copy Shared Files — 2026-08-14T07:15:18.118Z

Copied `./INSTRUCTION.md` → `tasks/task_1652_bottled_water_plant_source_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T07:41:41.235Z

All contracts pass. The PRD is complete. Here is the final summary.

## Done

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/workspace/PRD.md`

**Document structure** (designed from the domain, not the example's skeleton):
- §1 Introduction — 2 paragraphs from the regulatory/business-context angle (permit caps, disinfection validation, label law, recall traceability, sanitation loop, community reporting; `/api` mount; logical-clock rationale).
- §2 Global Specifications — 11 subsections: RBAC with all six roles and per-role opaque-identity prose; verbatim §2.2 response envelope (byte-compared against `section-2.2-response-structure.md`, PASS); pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending); the logical clock (default `2026-08-01T00:00:00Z`, never wall-clock) plus the wash-cycle injection capability; common resource properties for all 12 entities; cascade/version semantics; the full 11-rung validation priority ladder with the fixed sub-orders for safety (6), referential (8), and capacity (9) rungs; the three OCC rules; precision/rounding rules; segregation of duties; provisional-vs-certified dual accounting (withdrawal aggregates and bottle pools).
- §3 Business Logic — 9 subsections organized by lifecycle process (permits/withdrawals → compliance run & posture → treatment → lab testing → preform ledger → lots → recalls → bottle loop/wash → community reports), with constants embedded in context, parameters scattered across subsections (e.g., OCC fields live in §2.8 and recur in §3.1/3.5/3.6), and every error ID placed near its trigger.
- §4 Endpoint table — 72 rows, 4 columns only. §5 Error catalogue — 40 rows, 2 columns only (statuses from the scaffold catalog, including the 422 outliers `ERR_EMPTY_RECALL_SCOPE`, `ERR_RECOVERY_EXCEEDS_SCOPE`, `ERR_METER_READING_MISMATCH`, `ERR_OVERPRODUCTION`).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body: 53 required, 53 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- endpoints[].path_params: 4 required, 4 present, 0 missing (inside §4 backticked paths, as in the reference example)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 rungs checked, 11 expressed in prose (§2.7 ladder with fixed sub-orders), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write capability + expected_permit_version/expected_line_version + ERR_STALE_PERMIT_VERSION/ERR_STALE_LINE_VERSION + HTTP 412), 0 missing
- state_machines[].transitions: 53 checked (all 10 machines), 53 fully expressed with preconditions paired to error IDs and all cascade side effects, 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (cap enforcement equality, supersede exclusion, pinned verdict order with at-threshold-passes, per-source-then-sum rounding with 325,851 constant, reorder max/floor, 90% integer-ratio posture test, due-date defaults +7/+2/+1), 0 missing
- validations[] conditions: 40 error IDs checked, 40 matchable to triggers in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 72 checked, 72 expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/nullability expressed for all entities, 0 gaps
- sibling-branch symmetry: 10 groups checked (3 source classes, 3 test types, PASS/FAIL, ACCEPTED/REJECTED, SPRING/PURIFIED labels, provisional/certified, gross/sanitized, 2 washers, void/supersede, 3 suspension reasons), all with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 533
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate Unit Tests — 2026-08-14T08:16:04.492Z

All 114 tests collect cleanly. The generation is complete.

## Summary

Generated the complete test infrastructure and suite for `task_1652_bottled_water_plant_source_compliance`, translating exactly the two design indices (no freelance SCAFFOLD walking).

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 13 status/role enums + 13 entity TypedDicts (all entities carry `id`/`created_at`/`updated_at`/`version` per PRD §2.5; no append-only entities here).
- `api_client.py` — `ApiClient(GenericApiClient)` with 58 methods, one per PRD §4 endpoint row (including `_clock/set_current_utc` and `_inject/bottle-wash-cycles`).
- `api_errors.py` — all 40 `ApiErrorId` values with the §5 HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` plus ledger/view invariant checkers (e.g. `preform_free == on_hand - reserved`, certified ≤ provisional).
- `constants.py`, `factories.py` — thresholds (UV 40.0, turbidity 0.3, rinse 71.1, 150-cycle ceiling, 325851 gal/acre-ft, 90% watch, TARGET_DAYS 2) and input-only payload factories.
- `test_users.py` — all six roles are `identity: opaque` in this PRD, so shared `TEST_USERS` constants are canonical; per-instance builders provided for SoD user-threading (pl-1 vs qa-1/qa-2).
- `fixtures.py` — composite helpers: `post_withdrawal_event` (OCC fresh-read), `create_validated_run`, `setup_line_with_preforms`, `create_lot_in_qa_hold`, `create_released_lot`, `setup_released_lot_scenario`, `loop_bottle_to_dirty`, `create_running_wash_with_bottles`, `wash_bottle_once`, `create_recall_for_lots`.

### Stage 2 — `test_suite/` (8 files, 114 tests)
- `test_01` permits/withdrawals, `test_02` dual accounting + gallon/cycle boundaries, `test_03` treatment verdict branching + cadence, `test_04` production lots, `test_05` bottle loop + recalls + preform compensation, `test_06` community reports + cascades + posture, `test_07` validations/RBAC/OCC, `test_08` read-surface sweep.

### Audit results (all green)
- **Difficulty queue:** all 18 instances have ≥2 tests (tags `Design: Difficulty/<rule_id>/<name>`).
- **Corner queue:** all 77 non-stub instances have ≥1 test (tags `Design: Corner/<section>/<name>`); all 14 `excluded_because:` stubs left untranslated with cross-references verified to resolve.
- **Tag hygiene:** 114 test functions = 114 tags, zero unknown/stub/duplicate tags, zero `skip`/`skipif`/`xfail`.
- **PRD citation pass:** 133 quoted segments across all docstrings verified verbatim against `workspace/PRD.md` (whitespace/markdown-normalized); two imprecise quotes were rewritten to match PRD text exactly.
- `pytest --collect-only` discovers all 114 tests with no import errors.

No instances failed the PRD-first filter — every non-stub instance had verbatim PRD coverage with uniquely-derivable outcomes, so nothing was skipped.

## Step 6: Generate Implementation — 2026-08-14T08:24:54.925Z

Complete. The Python + Flask implementation for task_1652 (Bottled Water Plant & Source Compliance) is in place at `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/workspace/implementation/`.

**Layout** (per the skill's mandated structure):
- `start.sh` — guarded install (`python3 -c "import flask"` check, so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — app assembly, envelope error handlers (404/405/generic), and an `after_request` posture/pool sweep
- `db.py` — empty-on-boot in-memory store, logical clock defaulting to exactly `2026-08-01T00:00:00Z`, UUID ids, `version`/`updated_at` touch helper
- `errors.py`, `response.py`, `middleware.py` — `ApiError` with scaffold error_ids/statuses; envelope with `meta.api_request_id` (`req_`-prefixed) / `api_request_timestamp` (3-fractional-digit ISO), `response_type`, `data`, and `limit`/`offset`/`total_count`/`has_more` pagination in meta; auth on `X-User-ID`/`X-User-Role` with the six roles
- `services.py` — serializers, provisional/certified withdrawal aggregates, preform free/reorder derivation, treatment/wash verdicts, community-report per-source round-then-sum (Decimal, ROUND_HALF_UP, 325851 gal/acre-ft, 3 decimals), permit-suspension cascade, posture/pool recompute
- `routes/` — 11 modules covering all 72 endpoints

**Key fidelity decisions** (all traced to PRD/scaffold):
- Validation ladder enforced in priority order: auth → role → existence → OCC (`expected_permit_version`/`expected_line_version`, 412) → state → safety gates (SoD → treatment → product-test → sanitation → label → posture → reinstate) → temporal → cross-reference → capacity → quantity accounting → input shape (400 last)
- Cap checks use the provisional view keyed on the new event's date, excluding the supersede target, equality allowed, daily before monthly; supersede of a FINALIZED event locked by a PUBLISHED report (rung 7) before `ERR_SUPERSEDE_TARGET_INVALID` (rung 8)
- Compliance run in pinned 7-step order returning `{ops_run_index, events_finalized, tests_flipped, tests_auto_created, permits_suspended, permits_expired, posture}`; auto-created lab tests carry `origin: AUTO` with type-specific due-date defaults (+7d/+2d/+1d)
- Posture: exact integer 90% watch test (`prov*100 >= 90*monthly_cap`); sweep bumps plant `version` only when a derived value actually changes; permit/line versions bump exactly where the endpoint table documents
- Treatment verdict order turbidity → UV → ozone → spring-micro/RO branch; boundaries pass at threshold; wash verdict 71.1/50.0; lot windows half-open (touching OK), washer windows strict-overlap plus 30-minute purge in both directions
- No seeding: store boots empty; verified two consecutive `bash start.sh` launches come up with the default clock and empty collections

**Verification**: 100+ ad-hoc smoke assertions across six suites all pass — auth ladder, OCC 412s, cap/meter/window/future-date errors, void vs supersede, finalize-on-run, suspend cascades (run cancellation + BREACH) and reinstate guards, SoD on validate/release, label eligibility, window/purge conflicts, preform ledger math, overproduction 422, recall quarantine/recovery/close, sanitation fill gate, 150-cycle limit via the injection endpoint, report rounding order (0.307 + 1.000 = 1.307), publish gate, period lock release on supersede, and pagination/envelope shape.

## Step 7: Run Tests and Iterate — 2026-08-14T08:37:39.263Z

All 8 rounds pass 114/114 — clean sweep achieved.

## Summary

**Iterations run:** 2 eight-round parallel sweeps (initial diagnostic + verification).

**Failure profile (sweep 1):** 4 tests failing deterministically in all 8 rounds (union = 4; no flakiness observed). 110/114 passing.

**Tests deleted:** None.

**Fixes applied to `test_suite/` (4 edits, all test bugs — implementation was PRD-faithful throughout):**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/test_suite/test_03_treatment_validation_and_cadence.py` — `test_testing_due_schedule_type_defaults`: three `validate_success(api.create_lab_test(...))` calls lacked `expected_status=201`. PRD §4 verbatim: "Operations that create a new resource return `201 Created`." The asserted rule (due-date defaults, §3.4) is PRD-covered; only the status expectation was wrong. Added `expected_status=201`.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/test_suite/test_05_bottle_loop_and_recalls.py` — `test_washer_purge_buffer_thirty_minute_semantics`: two `validate_success(api.create_wash_batch(...))` calls (the w4/w5 creations) lacked `expected_status=201`. Same PRD §4 test bug; purge-buffer assertions themselves are verbatim §3.8. Fixed.

3. Same file — `test_bottle_duplicate_code_rejected`: the plant-B `validate_success(api.create_bottle(...))` call lacked `expected_status=201`. Same PRD §4 test bug; uniqueness rule is verbatim §3.8. Fixed.

4. `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/test_suite/test_07_validations_rbac_occ.py` — `test_updated_at_refreshes_on_mutation`: STEP 1b/1c split. The assertion `permit_after["updated_at"] != ua0` is not uniquely derivable: PRD §2.5 requires `updated_at` "refreshed on any change" but never names its clock source, while §2.4 states the logical clock "never falls back to wall-clock time" and defaults to a fixed instant. A faithful logical-clock implementation re-stamps the identical value under a frozen clock (test fails); a wall-clock implementation shows a delta (test passes). Removed only that inequality assertion; kept the PRD-covered assertions (permit `version` +1 per §3.1 "a plain create does the same"; `withdrawn_month_provisional_gallons == 250` per §2.11). Collapse pattern: unique-derivability miss on observable timestamp delta (clock-source silence) — feedback for unit-test-generator.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `implementation/`:** None — the implementation was fully PRD-faithful; every failure traced to test-side artifacts.

**Final state:** sweep 2 — all 8 rounds 114/114 passed, union of failures empty.

## Step 8: Finalize PRD — 2026-08-14T08:43:08.347Z

Done. `PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/workspace/PRD_FINALIZED.md` with exactly one in-place revision.

## Line counts / delta
- `PRD.md`: 340 lines; `PRD_FINALIZED.md`: 340 lines — 0 lines added/removed (0.0% delta). The single change is an inline revision within the §2.5 paragraph (line 82).

## Changes (one bullet per change)
- **§2.5 — revise** — Appended a clock-source pinning sentence to the common-resource-properties paragraph: "Both `created_at` and `updated_at` are stamped from the logical clock of §2.4, never from wall-clock time; while the logical clock is frozen, a change therefore re-stamps the identical `updated_at` value, and the `version` increment is the observable signal of the mutation." — `implementation/db.py:57-59` (`new_resource` stamps both fields from `store.clock`), `implementation/db.py:65-68` (`touch` re-stamps `updated_at` from `store.clock`).

## Disposition of the four step_7_diff items
1. `test_03` lab-test creates missing `expected_status=201` — pure test bug. PRD §4 already pins 201 for creates verbatim; impl returns 201 at `implementation/routes/labtests.py:106`. No PRD edit.
2. `test_05` wash-batch creates (w4/w5) missing `expected_status=201` — pure test bug; impl returns 201 at `implementation/routes/wash.py:94`. No PRD edit.
3. `test_05` plant-B bottle create missing `expected_status=201` — pure test bug; impl returns 201 at `implementation/routes/bottles.py:52`. No PRD edit.
4. `test_07` `updated_at != ua0` inequality removed — genuine PRD silence (§2.5 says "refreshed on any change" but never names the clock source; §2.4's enumeration doesn't cover resource timestamps). This produced the single edit above.

## Pre-edit search log (mandatory, for the one edit)
- **(a) Subject:** clock source for the §2.5 system-managed resource timestamps `created_at` / `updated_at`.
- **(b) Impl paths enumerated and read/grepped:**
  - Stamp helpers: `implementation/db.py:11` (STARTUP_CLOCK), `db.py:44-47` (`fmt_ts`, 3-fractional-digit ISO 8601 UTC), `db.py:50-51` (`wall_ts`), `db.py:54-62` (`new_resource`), `db.py:65-68` (`touch`), `db.py:71-74` (`by_creation` sort).
  - Every `new_resource(...)` callsite: `routes/plants.py:63`, `permits.py:53`, `withdrawals.py:143`, `treatment.py:51`, `services.py:308` (lab tests), `lines.py:27` and `lines.py:92`, `lots.py:122`, `recalls.py:67`, `bottles.py:40`, `wash.py:80`, `reports.py:63` and `reports.py:145`.
  - Every `touch(...)` callsite across all route files (full grep enumeration — all mutation and cascade paths).
  - Other stamped timestamp fields: `routes/plants.py:88,109` (`finalized_at`, logical clock — already pinned by PRD §3.1), `routes/reports.py:130` (`published_at`, logical clock — already pinned by PRD §3.9).
  - `implementation/response.py:18` — envelope `api_request_timestamp` uses `wall_ts()` (wall clock); PRD §2.2 names no clock for it.
  - Verified via grep (`wall_ts|datetime.now|fmt_ts(store.clock)|store.clock`) that no code path stamps resource timestamps from anything but the logical clock.
- **(c) Wording adjustment:** the new sentence is scoped to name only `created_at` and `updated_at`, deliberately avoiding any claim about the envelope's `api_request_timestamp` (wall-clock at `response.py:18`) and avoiding any extension of §2.4's enumeration; the frozen-clock consequence clause only restates what `fmt_ts(store.clock)` plus the already-pinned `version` rule jointly imply, so every enumerated create/mutate/cascade path — including the cascade touches in `services.suspend_permit`, `services.sweep`, and the compliance run — is described correctly.

## Step 9: Complete PRD — 2026-08-14T08:59:42.743Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1652_bottled_water_plant_source_compliance/workspace/PRD_COMPLETED.md` produced.

**Source vs output:** `PRD_FINALIZED.md` 340 lines / 56,959 chars → `PRD_COMPLETED.md` 340 lines / 59,360 chars (char-delta +2,401; all edits are in-paragraph inserts/revisions, no new sections, no new paragraphs).

**Counts:** 17 ambiguity-pins, 0 mismatch-revisions. The implementation matched every pinned PRD rule I checked (validation ladder order and sub-orders, OCC placement, cap/threshold arithmetic, state machines, cascades, filters, roles, rounding), so no PRD prose contradicted impl; all changes pin previously unpinned interpretations.

Changes (all ambiguity class):

- §2.2 — insert — ambiguity — envelope `api_request_timestamp` pinned as wall-clock-stamped, not logical-clock — `implementation/response.py:18`, `implementation/db.py:50-51`
- §2.3 — insert — ambiguity — unparseable `limit`/`offset` fall back to defaults; out-of-range values clamp to bounds (1–100 / 0) rather than erroring — `implementation/response.py:38-57`
- §2.3 — insert — ambiguity — `created_at` sort ties fall back to creation (insertion) order, including the §3.9 per-source breakdown — `implementation/db.py:71-74`, `implementation/services.py:199`
- §2.4 — insert — ambiguity — wash-cycle injection: unknown `bottle_id` → `ERR_NOT_FOUND`, negative/non-integer count → `ERR_INVALID_REQUEST`, any non-negative integer accepted, returns updated bottle — `implementation/routes/plants.py:38-53`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `implementation/db.py:54-62`
- §2.6 — insert — ambiguity — a recomputation leaving the derived value unchanged is not a mutation (no `updated_at`/`version` effect) — `implementation/services.py:286-303`
- §2.7 (rung 11) — insert — ambiguity — malformed or non-object JSON body → `ERR_INVALID_REQUEST` (400) — `implementation/services.py:22-31`
- §3.1 — insert — ambiguity — the four permit aggregates are derived at read time; finalization's "refresh" does not increment the permit's `version` — `implementation/routes/plants.py:100-111`, `implementation/services.py:95-113`
- §3.1 — revise — ambiguity — reinstate's "most recent completed test" pinned as greatest by `collected_at`, ties toward later `created_at`, then later creation order — `implementation/routes/permits.py:132-142`
- §3.2 — revise — ambiguity — plant creation payload pinned: `PlantAdmin` supplies `name` — `implementation/routes/plants.py:56-73`
- §3.3 — insert — ambiguity — validating a run whose parameters were never recorded yields FAIL, and SoD does not bind while `parameters_recorded_by_user_id` is null — `implementation/services.py:169-170`, `implementation/routes/treatment.py:156-161`
- §3.4 — insert — ambiguity — manually scheduled test with a subject belonging to another plant → `ERR_CROSS_PLANT_REFERENCE`, fired after existence and before the subject/type match — `implementation/routes/labtests.py:68-84`
- §3.4 — insert — ambiguity — failing `SOURCE_RAW` result on a permit no longer `ACTIVE` leaves status/`suspension_reason` unchanged, no cascade — `implementation/routes/labtests.py:159-162`, `implementation/services.py:226-229`
- §3.7 — insert — ambiguity — recall scope lot from another plant → `ERR_CROSS_PLANT_REFERENCE`, checked before the `RELEASED`-state requirement — `implementation/routes/recalls.py:36-50`
- §3.8 — insert — ambiguity — `bottle_count` is derived at read time; bottle assignment mutates only the bottles and does not increment the batch's `version` — `implementation/routes/wash.py:173-177`, `implementation/services.py:149-154`
- §3.8 — insert — ambiguity — starting a batch while another is `RUNNING` on the same washer → `ERR_INVALID_STATE` (409) — `implementation/routes/wash.py:186-194`
- §3.9 — insert — ambiguity — report supersede returns the successor with HTTP 200 (transition, not a plain create) — `implementation/routes/reports.py:160`
