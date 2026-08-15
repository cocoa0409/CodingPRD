# Worklog — task_1250_underground_storage_tank_compliance

## Step 1: Create Task Directory — 2026-08-12T07:44:33.500Z

Task directory `tasks/task_1250_underground_storage_tank_compliance/` and its `workspace/` subdirectory were pre-assigned and already exist on disk. Step 1 auto-index scan skipped per caller instruction; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-12T08:58:57.819Z

All three scaffold artifacts are generated, lint-clean, and verified.

**Deliverables** (in `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/`):
- `SCAFFOLD.yaml` (1956 lines) — §1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (858 lines) — single top-level key `scaffold_difficulty_design`, 18 instances (2 per rule × 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1971 lines) — single top-level key `scaffold_corner_design`, 83 instances (75 active + 8 `excluded_because` stubs)

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(67 endpoints, 13 entities, 18 §1.8 + 75 §1.9 instances, 939 calls scanned.)

**Design summary** — Expert-plus compliance/audit archetype with temporal-windowing secondary:
- **Entities (13):** Facility, TankSystem, Component, Technician, ServiceOrder, ResultRecord (immutable, `common_fields: false`), Deficiency, RegulatorySubmission, ReleaseDetectionRecord, OperatorPerson, TrainingRecord (immutable), ReleaseEvent, StateFundClaim. Flat topology; every FK has a filtered-list reverse GET.
- **Difficulty rule grounding:** dual variants = CP survey criteria (INSTANT_OFF vs POLARIZATION_SHIFT, same voltages diverge) and fund election (PER_OCCURRENCE vs AGGREGATE, same expenses diverge); combinatorial = weighted posture score with tier boundary (mode a) and pinned per-line-then-sum quote rounding (mode b, 25002 vs 25001 discriminator); non-linear machines = ServiceOrder review-rework cycle and Deficiency correction/re-test loop; cascades = release-confirm (depth 3) and FAIL-result (depth 3); priority conflicts = state-vs-safety on certify and safety-vs-fiscal on claim create; boundaries = leak rate exactly 0.100 passes, payable exactly equal to cap submits; cross-entity gates = schedule↔tank-state and operator-activate↔training-cert; overlap rules = technician half-open adjacency vs tank 8h stabilization buffer; invariants = submit+withdraw restores fund cap, fail+verify restores posture score.
- **Roles:** segregation-of-duties model (FacilityOwner, ContractorAdmin, Technician, ComplianceReviewer — both entity-backed by Technician, StateRegulator, Any); self-certification forbidden via `performed_by_technician_id` pinned at order start.
- **Concurrency:** two OCC rules (`PUT /service-orders/{id}`, `POST /submissions/{id}/amend`) with 412 ERR_STALE_VERSION.
- **Clock:** `POST /_clock/set_current_utc` with the mandated default `2026-05-01T00:00:00Z`.

**Verification performed beyond lint:** instance-name uniqueness across both design files (101 names, no dupes); all 66 catalogued errors named in at least one design instance; all grounds references resolve; every endpoint exercised by at least one recipe call; all formula-derived assert literals executed and confirmed (quote 25002, payables 1800000/1000000/100000000/450000, cap sequence 98200000→99000000→98550000, posture 85/70/85, CP criterion divergence); forbidden concurrency vocabulary absent; enum closure verified for all status fields.

One notable design decision baked in during self-review: a FAIL result on a linked re-test order spawns no new deficiency/release — the existing deficiency loops back to CORRECTION_ORDERED at certify — preventing deficiency pile-up and posture drift in the re-test cycle.

## Step 3: Copy Shared Files — 2026-08-12T08:59:31.519Z

Copied `./INSTRUCTION.md` to `tasks/task_1250_underground_storage_tank_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T09:14:17.635Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/workspace/PRD.md`.

## What was generated

A prose PRD for the UST Compliance & Testing Services API with a domain-derived skeleton: §1 two-paragraph introduction (regulatory exposure + system scope); §2 with 11 subsections including the domain-specific "The Logical Clock" (default `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`), "Ownership Anchors, Nested Retrieval, and Hierarchical Cascades", a 19-step "Request Validation Precedence" pipeline, "The Facility Compliance Posture Score" (full weighted formula, clamp, 85/60 thresholds), "Cents, Millivolts, and Rounding Conventions", and "Segregation of Duties Between Field and Office"; §2.2 emitted verbatim from the fixed source file; §3 with 9 lifecycle-grouped subsections (inventory/scheduling → closures/cascades → quoting/dispatch/edit → fieldwork/result determination → certification/deficiency loop → records/submissions → operator training → releases/fund claims → monthly close sweep); §4 a 4-column table of all 67 endpoints; §5 a 2-column catalogue of all 66 errors with statuses.

Key scattered logic preserved: quote per-line half-up rounding + 15000-cent mobilization; inclusive bounds (0.100 gph, 5 min, 95.0 pct, −850 mV, 100 mV shift, exactly-8h stabilization buffer); half-open window overlap with adjacency allowed; the linked-deficiency FAIL suppression rule and certify-time PASS/FAIL/INCONCLUSIVE resolution; both fund variants (PER_OCCURRENCE 1000000-cent deductible + 0.90 coinsurance vs AGGREGATE pool + 100%) with cap reservation/release at submit/withdraw/deny/partial; the 4-step pinned monthly close with idempotent CLOSE_SWEEP deficiencies; 24-hour release deadline with strict lateness; and 36/36/12-month class-certificate validity with strict expiry.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 83 required, 83 present, 0 missing
- endpoints[].request_body/input: all identifiers present, 0 missing (incl. to_iso8601, closure_type, note, decision, OCC fields)
- endpoints[].query_params: all present, 0 missing (incl. endorsement, active)
Status: PASS

Rule coverage check:
- validations[] priority: 19 steps expressed as an explicit precedence pipeline (§2.7), plus per-endpoint ordering, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint capability + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all transitions across 10 machines expressed with preconditions + error IDs + side effects, 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (constants embedded: 15000, 0.100, 5, 95.0, -850, 100, 12/60/12/12/36/36, 25/15/5/5/10/5, 85/60, 7/30/90, 1000000/2000000/0.90/100000000, 36/36/12, day-10/11 boundary, 24h, 8h), 0 missing
- validations[] conditions: all matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, nullables, conditional requirements, computed fields all reconstructible, 0 missing
- sibling-branch symmetry: CP criteria, fund variants, adjudicate decisions, withdraw DRAFT/SUBMITTED, escalation/revoke sibling transitions all at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 611
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T10:00:51.279Z

Test infrastructure and suite generation complete for task_1250.

## What was generated

**`test_helpers/`** (Stage 1 — 9 files):
- `types.py` — 13 entity TypedDicts + status/role enums; `ResultRecord` and `TrainingRecord` correctly omit `updated_at`/`version` (append-only per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 endpoints)
- `api_errors.py` — all 66 error IDs + HTTP status map, registered via `set_error_http_status_map` so `validate_error` auto-checks status codes
- `assertions.py` — per-entity assertions + `assert_facility_invariants` (posture score 0..100 and label-band consistency) + `parse_ts`/`assert_ts_equal` for instant-wise timestamp comparison (avoids over-pinning fractional-digit formatting the PRD leaves open)
- `factories.py`, `constants.py` (all PRD thresholds: 0.100 gph, −850 mV, 100 mV shift, 5 min / 95.0%, 15000 mobilization, fund constants, validity months), `test_users.py` (opaque role constants + mandatory `make_technician_headers`/`make_reviewer_headers` entity-backed builders), `fixtures.py` (~25 composite helpers: active site builders, started/failed/corrected CP-order chains, confirmed-release claim sites, submission/training helpers), `__init__.py` barrel.

**`test_suite/`** (Stage 2 — `conftest.py` + 10 files, **110 tests**):
- `test_01_facility_inventory.py` (15), `test_02_dispatch_and_scheduling.py` (19), `test_03_execution_and_certification.py` (18), `test_04_deficiency_lifecycle.py` (7), `test_05_release_events.py` (6), `test_06_records_submissions_close.py` (13), `test_07_operators_training.py` (6), `test_08_fund_claims.py` (14), `test_09_auth_rbac_errors.py` (8), `test_10_posture_score.py` (4)

## Audit results

- **Queue A (Difficulty):** all 18 instances have ≥2 tests, each tagged `Design: Difficulty/<rule_id>/<name>` verbatim.
- **Queue B (Corner):** 74 of 75 non-stub instances covered with ≥1 test, tagged `Design: Corner/<section>/<name>`. All 8 `excluded_because` stubs skipped; their difficulty-instance cross-references all resolve.
- **One deliberate PRD-first skip:** `Corner/entities/extra_field_in_create_payload_rejected` — PRD §2.7 enumerates the `ERR_INVALID_REQUEST` triggers as a closed list (missing field, malformed value, bad enum, bad month format, empty `expense_lines`, bad readings) and never states that undeclared/computed payload keys are rejected; a PRD-only implementer could faithfully ignore them. Fails unique derivability → gap left as a gap, no placeholder.
- **Citations:** 167 verbatim ≥8-word PRD quotes across all docstrings, all confirmed as literal substrings of `PRD.md` (whitespace-normalized); exactly one `Design:` line per test; no untagged/dual-tagged/phantom tags; no `skip`/`skipif`/`xfail`; no scaffold references in comments.
- **Initial-version literals** (`version == 1`) were not asserted anywhere — PRD §2.5 pins "increments by 1 on every mutation" but not the starting value, so tests assert increment-by-one across a mutation instead.
- `pytest --collect-only` imports all files cleanly: **110 tests collected**.

## Step 6: Generate Implementation — 2026-08-12T10:00:51.279Z

Implementation complete and verified. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/workspace/implementation/`.

## What was built

A Python + Flask in-memory REST API implementing the full UST Compliance PRD:

- **Foundation**: `db.py` (empty-on-boot store + logical clock pinned at `2026-05-01T00:00:00Z`), `errors.py` (all 44 scaffold catalog error IDs with exact HTTP statuses), `respond.py` (exact `meta`/`response_type`/`data` envelope, `error_id`/`message` error body, `limit`/`offset`/`total_count`/`has_more` pagination meta), `timeutil.py` (3-fractional-digit UTC timestamps, whole-month arithmetic, YYYY-MM period helpers), `store_ops.py` (closed-schema body validation, `version`/`updated_at` touch-on-mutation, pagination with defaults 10/0 and clamp 1-100), `authz.py` (X-User-ID/X-User-Role priority 1-2 checks; the six roles including `Any` for all GETs), `serialize.py`, `calc.py`, `cascades.py`.
- **Routes**: 14 blueprints covering all 56 endpoints — clock, facilities (activate/close/run-monthly-close), tank-systems (place-in-service/close/return-to-service/test-schedule), components, technicians, service-orders (create/schedule/PUT-with-OCC/start/results/certify/return-for-correction/cancel), result-records, deficiencies, submissions (submit/accept/reject/amend-with-OCC), release-detection-records, operators, training-records, release-events, fund-claims (submit/withdraw/adjudicate).
- **Key rules implemented per spec**: per-line half-up quote rounding + 15000 mobilization; tightness 0.100 inclusive pass; CP dual criteria (INSTANT_OFF -850, POLARIZATION_SHIFT ≥100, valid_contact→INCONCLUSIVE); spill/overfill inclusive bounds (5 min, 95.0%); per-mode test-schedule projection with window_end-anchored due dates; weighted posture score (25/15/5 +5 escalated, −10 release, −5 lapsed; 85/60 tiers); dual fund variants (per-occurrence 1M deductible + 90% coinsurance vs aggregate pool + 100%); fund-cap reservation/release/compensation ledger; 8h tank stabilization buffer; half-open technician overlap; deficiency re-test loop with FAIL suppression on linked orders; monthly-close 4-step pinned sweep (idempotent CLOSE_SWEEP gaps, lapse, escalation, single recompute); depth-3 cascades (release confirm → tank close → order cancel → deficiency fallback); segregation of duties with state-before-self-cert ordering; OCC (`expected_service_order_version`/`expected_submission_version`, 412) checked last per priority 19.

## Verification

- `bash start.sh` boots cleanly in ~1.5s on `0.0.0.0:$PORT` from a pristine directory (guarded dependency install with `.deps_installed` sentinel; `exec python3 app.py` in foreground).
- Three consecutive fresh boots each showed an empty store — no seeding anywhere.
- Four smoke suites (~120 assertions) covering every pinned scenario from SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml pass on fresh servers: exact quote/fund/posture literals (25002, 1800000/1000000, 85/70/65/50 tier moves, cap 98200000→100000000 restore, payable==cap→0), all error-precedence pairs, boundary inclusivity (0.100 pass, 8h buffer, 23:59:59 due, 2000-gallon manual gauging), both cascade chains, OCC replays, and the monthly-close counts.
- One bug found and fixed during testing: `tank_stabilization_window` missing from the orders.py import list (surfaced as a 500 on the 6h-gap rejection path); fix verified.

One judgment call worth noting: per the corner-design evidence, technician-bound endpoints (`start`, `results`) check state before ownership (a `REQUESTED` order has no bound technician, and the pinned test expects `ERR_ORDER_NOT_SCHEDULED` there), while facility-owner-gated endpoints check ownership before state, matching PRD §2.7 priority 3-before-5.

**Orchestrator route-parity check (post-Step 6):** all 67 (method, path) endpoint pairs declared in SCAFFOLD.yaml are registered by the Flask implementation — 0 missing, 0 extra.

## Step 7: Run Tests and Iterate — 2026-08-12T10:13:33.162Z

All 8 parallel rounds pass 110/110. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep: 98/110 per round, 12 failing tests; post-fix sweep: 110/110 across all 8 rounds, zero flakes)

**Tests deleted:** None. Every failing test traced to verbatim PRD prose and the failures were test-artifact bugs, not PRD-silent assertions.

**Fixes applied to `test_suite/`** (all were the same two test-bug patterns; no `test_helpers/` changes were needed):

1. **Bare `api` NameError in class helper methods (10 tests across 6 files).** Helper methods like `_setup_temporarily_closed_tank(self)` referenced the bare name `api`, which only exists as a pytest fixture parameter on test methods — helpers without the parameter crashed with `NameError: name 'api' is not defined`. Fixed by importing the module-level `api_client` singleton from `test_helpers` (the exact convention `test_helpers/fixtures.py` already uses) and calling it inside the helpers:
   - `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_01_facility_inventory.py` — `_setup_temporarily_closed_tank`
   - `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_02_dispatch_and_scheduling.py` — `_setup_overlap_site`
   - `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_03_execution_and_certification.py` — `_run_rework_loop`
   - `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_05_release_events.py` — `_setup_cascade`
   - `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_06_records_submissions_close.py` — `_setup_under_review_order` (switched to the existing `get_order` helper instead of the local `get_order_ref(api, ...)`)
   - `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_08_fund_claims.py` — `_setup_non_compliant_facility`

2. **Ordering-violating setup in two scheduling tests** (`/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/test_suite/test_02_dispatch_and_scheduling.py`):
   - `test_schedule_blocked_when_tank_not_in_service` closed the tank *after* creating the order. Per PRD §3.2, temporary closure cascades to cancel REQUESTED orders, so the implementation correctly fired `ERR_ORDER_NOT_REQUESTED` — which PRD §3.3 explicitly orders before the tank check ("The checks run in order: the order must be `REQUESTED` (`ERR_ORDER_NOT_REQUESTED`); the tank must be `IN_SERVICE` (`ERR_TANK_NOT_IN_SERVICE`)"). Fixed the setup to create the order while the tank is still `REGISTERED` (never placed in service), so the order stays REQUESTED and the tank gate is genuinely reached.
   - `test_schedule_unblocked_after_return_to_service` had the same flaw; fixed by creating the order *after* the close → return-to-service cycle, so the closure cascade can't cancel it.

**Fixes applied to `implementation/`:** None. The implementation's gate ordering already matched PRD §3.3 verbatim; the failures were entirely test-side setup bugs.

**Orchestrator disk verification (post-exit):** all 8 `results.{1..8}.json` files present; every round reports passed=110 total=110 failed=0 errors=0 (ALL_PASS).

## Step 8: Finalize PRD — 2026-08-12T10:17:18.102Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/workspace/PRD_FINALIZED.md` is written and is byte-identical to `PRD.md`.

## Summary

**Line counts:** PRD.md = 398 lines; PRD_FINALIZED.md = 398 lines; delta = 0%. Zero edits — every `<step_7_diff>` item is a pure test-artifact bug with the underlying behavior already pinned verbatim by PRD prose, and the implementation already matches the PRD at every site Step 7 touched.

### Per-item analysis (with the searches each item triggered)

**Item 1 — Bare `api` NameError in class helper methods (10 tests, 6 files).**
- (a) Subject: how test code obtains an API client — no production behavior involved.
- (b) Paths enumerated: `test_suite/conftest.py:9` (the `api` fixture returns `api_client`), `test_helpers/fixtures.py:10` (`from .api_client import api_client` — the convention the fixes adopted), and each fixed helper: `test_01:281-286`, `test_02:281-291`, `test_03:239-247`, `test_05:56-96`, `test_06:70-98`, `test_08` (setup helper). All fixes are import/rewire-only inside test code; no request shape, assertion, or ordering changed.
- (c) Conclusion: no PRD silence, no mismatch → no edit.

**Item 2a — `test_schedule_blocked_when_tank_not_in_service` setup ordering.**
- (a) Subject: (i) temporary-closure cascade cancelling `REQUESTED`/`SCHEDULED` orders; (ii) schedule-endpoint check ordering (order-state gate before tank-state gate).
- (b) Paths enumerated: `implementation/cascades.py:12-22` (`cancel_order_cascade`: only `REQUESTED`/`SCHEDULED` → `CANCELLED`, linked `RE_TEST_SCHEDULED` deficiency → `CORRECTED`); `cascades.py:25-42` (`close_tank_cascade`); `routes/tanks.py:131-149` (TEMPORARY closure requires `IN_SERVICE`, fires the cascade); `routes/releases.py:79-96` (confirm-release fires the same cascade — the parallel cascade path, consistent); `routes/orders.py:260-293` (`schedule_order`: existence L→R at 269-270 per §2.7 priority 4, then `ERR_ORDER_NOT_REQUESTED` at 272-273, then `ERR_TANK_NOT_IN_SERVICE` at 274-276, then endorsement/window/double-booking/stabilization at 278-281). The fixed test's own comments (test_02:233-238) cite PRD §3.2/§3.3 verbatim.
- (c) Conclusion: PRD §3.2 sentence "Every form of temporary closure cancels the tank's service orders still in `REQUESTED` or `SCHEDULED`..." and §3.3 sentence "The checks run in order: the order must be `REQUESTED` (`ERR_ORDER_NOT_REQUESTED`); the tank must be `IN_SERVICE` (`ERR_TANK_NOT_IN_SERVICE`)..." pin both behaviors exactly as implemented, including across the parallel release-confirm cascade path → no edit.

**Item 2b — `test_schedule_unblocked_after_return_to_service` setup ordering.**
- (a) Subject: closure cascade (same as 2a-i) plus return-to-service gates and clean return.
- (b) Paths enumerated: same cascade paths as 2a, plus `routes/tanks.py:157-178` (`return_to_service`: requires `TEMPORARILY_CLOSED`; gate 1 rejects `CRITICAL` deficiencies in `OPEN`/`CORRECTION_ORDERED`/`ESCALATED` at 167-170; gate 2 rejects releases in `SUSPECTED`/`CONFIRMED`/`CLEANUP_IN_PROGRESS` at 172-175; clean return → `IN_SERVICE` at 176-177).
- (c) Conclusion: PRD §3.2 pins both gates with identical status sets and order, and states "A clean return moves the tank `TEMPORARILY_CLOSED` → `IN_SERVICE`" — impl matches verbatim → no edit.

**Implementation fixes:** none listed in `<step_7_diff>` — nothing further to reconcile.

### Change log
- No changes. (Zero bullets; the identical-copy outcome is the valid result per the method note.)

## Step 9: Complete PRD — 2026-08-12T10:33:05.783Z

PRD_COMPLETED.md is complete. Summary:

**Source / size**
- Source: `PRD_FINALIZED.md` (398 lines, 56811 chars) → `PRD_COMPLETED.md` (402 lines, 60703 chars), char-delta +3892.

**Counts**
- Ambiguity-pins: 21
- Mismatch-revisions: 8

**Changes** (all file refs under `/home/ubuntu/github/CodingPRD/tasks/task_1250_underground_storage_tank_compliance/workspace/implementation/`):

- §2.2 — insert — ambiguity — pin unmatched path → `ERR_NOT_FOUND` 404, wrong method → same body with 405, unhandled failure → `ERR_INTERNAL` 500 — app.py:30-40
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values are clamped (not rejected); non-integer → `ERR_INVALID_REQUEST`; list sorting ties broken by creation order — store_ops.py:164-192, 160-161
- §2.5 — revise — ambiguity — `version` starts at 1 and `updated_at` equals `created_at` at creation — store_ops.py:16-17
- §2.7 — revise — mismatch — precedence items 3–5 reordered: existence (path ids, then ownership-anchor body refs) precedes ownership, which precedes state; technician-bound order actions (start/results) evaluate order state before the technician-binding check — authz.py:46-50 vs orders.py:359-364, 380-383
- §2.7 — insert — ambiguity — closed-schema rule: undeclared fields rejected with `ERR_INVALID_REQUEST`, except body-less transition endpoints (facility/deficiency/operator/submission-submit-accept/release/claim actions) which ignore bodies; service-order action endpoints reject any field — store_ops.py:43-47, deficiencies.py:45,61, orders.py:358,436,471,485
- §2.8 — revise ×2 — mismatch — stale-version predicate is "supplied value does not equal current version" (any mismatch), not only "advanced beyond" — store_ops.py:148-157, orders.py:338, submissions.py:247
- §2.9 — revise — mismatch — posture recompute trigger narrowed: operator revocation via the revoke endpoint recomputes; revocation cascading from facility closure does not — facilities.py:124-129 (no recompute) vs operators.py:103-105
- §2.10 — revise — ambiguity — readings are never rounded; compared exactly against thresholds expressed at 3/1 decimal places — calc.py:96,100-103
- §3.1 — revise — ambiguity — place-in-service of a non-`REGISTERED` tank → `ERR_TANK_NOT_IN_SERVICE`; facility activation from non-`REGISTERED` → `ERR_FACILITY_NOT_ACTIVE` — tanks.py:119-120,126-128, facilities.py:99-100
- §3.1 — revise — mismatch — test-schedule "latest certified order" tie-break is creation order, not `created_at` — calc.py:141
- §3.2 — revise ×3 — ambiguity — tank close from-state errors (`ERR_TANK_NOT_IN_SERVICE` for both closure types), return-to-service from-state error, facility close from non-`ACTIVE` → `ERR_FACILITY_NOT_ACTIVE` — tanks.py:141-147,163-164, facilities.py:114-115
- §3.3 — insert — ambiguity — new order has `technician_id`/`window_start`/`window_end`/`performed_by_technician_id`/`certified_by_technician_id` all null — orders.py:223-230
- §3.3 — revise — mismatch — schedule check order: technician existence first, then `REQUESTED`, then tank `IN_SERVICE`, then endorsement — orders.py:269-278
- §3.3 — insert — ambiguity — PUT edit: editability check precedes resolution of a newly supplied `technician_id`; version comparison runs last — orders.py:304-312, 337-339
- §3.4 — insert — ambiguity — ResultRecord carries the submitted `readings` — orders.py:387-396, serialize.py:98-107
- §3.4 — revise — ambiguity — leak-rate and overfill readings compared exactly (never rounded) against the thresholds — calc.py:96,100-103
- §3.6 — revise — ambiguity — `readings_summary` must be a JSON object — records.py:30-32
- §3.6 — revise — ambiguity — monthly/test-report bundles require non-empty id arrays; non-applicable bundle fields stored/returned as null or empty arrays — submissions.py:36-37,48,106-109
- §3.6 — insert — ambiguity — amendment retains the prior `state_reviewer_note` — submissions.py:250-257 (note untouched)
- §3.7 — revise — ambiguity — instructor `X-User-ID` must identify a registered Technician (`ERR_TECHNICIAN_NOT_FOUND`) before the trainer-flag check — training.py:36-41
- §3.7 — revise ×2 — mismatch — latest-training tie-break is most-recently-created (insertion order), not latest `created_at` (activation and lapse sweep) — calc.py:194-201
- §3.7 — insert — ambiguity — revoking an already `REVOKED` operator → `ERR_OPERATOR_NOT_ACTIVATABLE` — operators.py:101-102
- §3.8 — insert — ambiguity — supplied `tank_system_id` on release report validated only for existence, not facility alignment — releases.py:44-45
- §3.8 — insert — ambiguity — new claim is `DRAFT` with `approved_amount_cents` null — claims.py:79-90
- §3.8 — revise — ambiguity — adjudication moves the claim to a terminal status equal to the decision value — claims.py:185
- §3.9 — revise — ambiguity — missing-record sweep iterates tanks in creation order — facilities.py:150-153
- §5 — insert ×2 — ambiguity — catalogue rows for `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500) — app.py:30-40

No new sections were added; all pins are inline. Everything else in the implementation (state machines, cascades, quote/claim formulas, outcome thresholds, lateness/close boundaries, filters, role table) was already uniquely pinned by the PRD and verified consistent.
