# Worklog — task_1371_medical_device_contract_manufacturing

Scenario: Medical Device Contract Manufacturing (ISO 13485) — design transfer & device master record, process validation (IQ/OQ/PQ) & revalidation trigger, lot/UDI traceability & label control, supplier qualification & change notification, nonconformance/CAPA & complaint linkage, sterile barrier & shelf-life study, quality agreement & audit rights, field-action support.

Difficulty target from user: HARDER THAN EXPERT LEVEL.

## Step 1: Create Task Directory — 2026-08-13T01:22:00.000Z

Pre-assigned by pipeline runner. `tasks/task_1371_medical_device_contract_manufacturing/workspace/` verified present; no index scan performed per instructions.

## Step 2: Generate Scaffold — 2026-08-13T02:38:00.000Z

All three files are complete, lint-clean, and self-audited. Summary:

## Task 1371 — Medical Device Contract Manufacturing (ISO 13485) scaffold

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/`):
- `SCAFFOLD.yaml` (2172 lines) — §1.0–§1.7 + `concurrency_rules`; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (937 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1719 lines) — single key `scaffold_corner_design`

**Counts**
- Entities: 16 (DMR w/ self-referential revisions, ManufacturingLine, Supplier, QualityAgreement, SupplierPart, SCN, SupplierAudit, ValidationProtocol, SterileBarrierStudy, DeviceLot, LotComponent, UDILabel, NCR, Complaint, CAPA, FieldAction)
- State machines: 14 — including cyclic (ValidationProtocol reject loops + 36-month revalidation re-entry; CAPA INEFFECTIVE loop; Supplier SUSPENDED⇄QUALIFIED; Complaint/NCR reopens) and parallel dimensions (DeviceLot `disposition_status` × `hold_status`)
- Calculations: 6 (lot expiry dual-variant, supplier score dual-variant, tiered sterile sampling, complaint-rate feedback-ordered, audit scheduling, GS1 UDI check digit)
- Endpoints: 96 · Errors: 46 · Roles: 6 (all `opaque`, all with SoD-relevant `X-User-ID` semantics)
- Concurrency rules: 2 — both true create-with-supersede OCC races (agreement-create on `Supplier.version`, revision-create on `DeviceMasterRecord.version`)

**§1.8 — 20 instances by rule**: dual_variant_calc 2, combinatorial_formula 2 (modes a + c), non_linear_state_machine 2, transitive_cascade 2 (NCR disposition depth-3 chain; CAPA process-change depth-2), priority_pair_validation_conflict 2 ((auth,state) and (business_temporal,business_referential)), boundary_precision_check 3 (score exactly 50 safe / 48 suspends; rate exactly 5.0000 flags / 4.9998 doesn't; audit notice 30 vs 29 days), cross_entity_state_dependency 3 (Supplier→Agreement, Lot→Protocol, Complaint→CAPA), resource_temporal_overlap 2 (half-open audits on Supplier vs buffered windows on ManufacturingLine), compensating_invariant 2 (component mass balance 1000=750+0+200+50; penalty reversal zero-drift).

**§1.9 — 77 instances by section**: entities 11, state_machines 19 (2 stubs), calculations 6 (3 stubs), validations 5 (2 stubs), endpoints 23, errors 1, rbac 6, cross_cutting_layers 5 (2 stubs), consistency_model 1 — 68 active, 9 `excluded_because` stubs all resolving to §1.8 names.

**Verification**: `scaffold_lint.py` verdict block (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (96 endpoints, 16 entities, 20+68 instances, 1272 calls scanned). Additional self-audits passed: zero unbound `${var}` placeholders, 98 globally unique instance names, all 46 errors referenced and triggerable, no forbidden race vocabulary, no duplicate names, all numeric assertions pre-computed in Python (UDI check digit `12345678901231`, expiry dates, sampling tiers 25→25/26→20/151→32/critical 100→30, rates 5.0000/4.9998, scores 50/48/70/85).

**Notable design decisions** (reachability-driven, replayed call-by-call): lot creation allows pre-VALIDATED protocols (release gates it, keeping ERR_PROTOCOL_NOT_VALIDATED single-failure reachable); NCR auto-hold applies only to IN_PRODUCTION lots so the ERR_OPEN_NCRS_EXIST release gate stays reachable on COMPLETED lots; label revision pinned against the currently-APPROVED family revision so ERR_LABEL_REVISION_MISMATCH fires after a supersede; complaint-rate recomputation has a pinned 5-step evaluation order (recall shrinks its own denominator → flag clears); clock endpoint fixed at default `2026-08-01T00:00:00Z` with monotonic sweeps driving agreement-expiry→supplier-suspension and time-expiry→revalidation cascades. Endpoint/entity counts deliberately exceed the Expert band per the harder-than-expert instruction — every endpoint is load-bearing (state transition, cascade source, OCC guard, or lint-required FK reverse reachability), not CRUD padding.

## Step 3: Copy Shared Files — 2026-08-13T02:39:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1371_medical_device_contract_manufacturing/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T03:05:00.000Z

All three hard contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/workspace/PRD.md`.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/workspace/PRD.md` — 438 lines.

**Section list:** §1 Introduction (2 paragraphs) · §2 Global Specifications with 12 subsections (2.1 RBAC, 2.2 API Response Structure [byte-identical verbatim block, appended directly from the source file], 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Time-Driven Sweeps, 2.6 Segregation of Duties, 2.7 OCC, 2.8 Cascading Propagation & Lot Hold Model, 2.9 Supplier Scoring/Risk Tiering/Audit Cadence, 2.10 Validation Order, 2.11 Nested Resource Retrieval, 2.12 Precision & Calendar Arithmetic) · §3 Business Logic in 7 domain-derived subsections (design transfer/revisions, sterile-barrier studies & shelf-life ladder, IQ/OQ/PQ validation pipeline, supplier lifecycle/agreements/audits, parts/receipts/SCNs, lot production/genealogy/labels, NCR/complaint/CAPA/field actions) · §4 Endpoint Definitions (4-column table, all 96 endpoints) · §5 Error Code Catalogue (2-column table, 47 IDs = 42 catalog entries + `ERR_UDI_CHECK_DIGIT_MISMATCH`, which the scaffold defines only inside validations §1.4/calculation `udi_check_digit` but which the lossless-projection rule requires).

**Coverage confirmation (machine-checked against the scaffold):**
- Contract 1 (field names): 130/130 required identifiers present in backticks (all entity fields, request-body keys, path params `supplierId`/`lotId`/`id`, query filters, clock output `current_utc`).
- Contract 3 (§3 path purity): 739 §3 backtick tokens scanned, 0 paths / 0 bare HTTP methods / 0 method+path combos.
- All 47 error IDs appear in prose; all 91 state/enum strings appear verbatim; all 6 role names exact; 96/96 endpoints in the §4 table.
- Contract 2 (rule coverage): all 14 state machines rendered transition-by-transition with preconditions paired to error IDs and every side effect stated; all 6 calculations rendered as reconstructible prose (dual-variant lot expiry with the 0.5-ratio/12-month provisional cap and 60-month final cap, dual-variant supplier scoring with 5/15/30 NCR and 2/8 audit penalties, 90/70 tier thresholds, sub-50 auto-suspend, the 3-lot maturity gate with 25/150/1200/10000 tier boundaries and single-ceiling 1.5× critical multiplier, the pinned 5-step complaint-rate evaluation order, the 24/12/6+12-month audit cadence with inclusive overdue comparison, and the GS1 check digit); the 12-priority validation pipeline stated as an explicit ordered list; both OCC rules fully specified (`expected_supplier_version` / `expected_dmr_version` → `ERR_STALE_VERSION` 412, plus the parent version increment on success).

**Key Zero-Silence decisions (behaviors pinned so tests uniquely derive them):**
1. **Line-window conflict rule**: conflict iff the gap between windows (earlier `planned_end` → later `planned_start`, either direction) is strictly less than `changeover_buffer_hours`; exactly-equal gap allowed; occupying statuses enumerated as DRAFT through PQ_REVIEW, excluding VALIDATED/REVALIDATION_REQUIRED.
2. **GS1 check-digit direction**: the scaffold's symbolic formula and its "weights 3,1 counting from the right" gloss disagree under 1-based indexing; I pinned the GS1-conventional reading (rightmost of the 13 digits weighted 3) matching the scaffold's own comment.
3. **Revision creation from non-APPROVED parent**: mapped to `ERR_DMR_NOT_APPROVED` (the catalog's "operation requires DMR APPROVED" error), since the scaffold names the requirement but not the error.
4. **Lot create vs. protocol VALIDATED**: the endpoint description explicitly allows pre-VALIDATED protocols at creation while the release gate enforces `ERR_PROTOCOL_NOT_VALIDATED`; the PRD states both halves verbatim-spirit ("production under validation-in-progress is permitted, while release is not").
5. **Recall vs. scrap label voiding asymmetry**: scrap voids DRAFT/APPROVED/PRINTED; recall voids only APPROVED/PRINTED (a DRAFT label survives a recall) — both branches stated with equal density.
6. **Cascade no-op on already-held lots**: pinned that the existing `hold_reason` is retained, not re-stacked.
7. **NCR creation hold scope**: applies to IN_PRODUCTION *and* COMPLETED lots (per state-machine notes, over the narrower endpoint summary); reopen re-holds only IN_PRODUCTION lots, with COMPLETED lots governed by the release gate.

## Step 5: Generate Unit Tests — 2026-08-13T03:55:00.000Z

All checks pass. Generation complete — final summary below.

## Summary

**Inputs read:** skill spec, SCAFFOLD.yaml, both design indices, PRD.md (all in full).

### Test counts

**Queue A (Difficulty) — 40 tests across all 20 instances (≥2 each):**
- dual_variant_calc: 4 (lot_expiry_provisional_vs_final, supplier_score_current_vs_finalized)
- combinatorial_formula: 4 (sterile_sample_qty_tiered_maturity, complaint_rate_feedback_evaluation_order)
- non_linear_state_machine: 4 (validation_protocol_reject_loop_and_revalidation_cycle, device_lot_parallel_disposition_and_hold)
- transitive_cascade: 4 (ncr_supplier_fault_disposition_chain, capa_process_change_revalidation_chain)
- priority_pair_validation_conflict: 4 (sod_vs_state_on_dmr_approve, temporal_vs_referential_on_scn_create)
- boundary_precision_check: 6 (supplier_score_exactly_50_not_suspended, complaint_rate_exactly_5_sets_flag, audit_notice_window_exactly_30_days)
- cross_entity_state_dependency: 6 (supplier_qualify_requires_active_agreement, lot_release_requires_validated_protocol, complaint_close_requires_capa_closed)
- resource_temporal_overlap: 4 (supplier_audit_half_open_adjacency, line_window_changeover_buffer)
- compensating_invariant: 4 (part_quantity_mass_balance, supplier_penalty_reversal_zero_drift)

**Queue B (Corner) — 67 tests across 67/68 non-stub instances:** entities 11, state_machines 17, calculations 3, validations 3, endpoints 22, errors 1, rbac 6, cross_cutting_layers 3, consistency_model 1. All 9 `excluded_because:` stubs verified to resolve to real queue-A instances and were not translated.

### Skipped instances (two-condition filter)

- **Corner/endpoints/release_with_open_ncr_on_completed_lot** — fails Coverage. The instance asserts an NCR on a COMPLETED lot places no hold and release fails `ERR_OPEN_NCRS_EXIST`. PRD §3.7 states the opposite verbatim: "when the referenced lot is `IN_PRODUCTION` or `COMPLETED`, it is placed `ON_HOLD` with `hold_reason` `NCR_OPEN`." Per PRD, that release fails earlier with `ERR_LOT_ON_HOLD` (pipeline step 8 masks step 9). Skipped, not weakened.

### Files

- `test_helpers/`: `__init__.py`, `types.py` (28 status enums + 17 TypedDicts), `api_client.py` (63 endpoint methods), `api_errors.py` (47 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + instant-equality + mass-balance/score invariants), `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (composite stacks: validated protocol pipeline, qualified supplier, releasable/released lots, NCR/CAPA walkers)
- `test_suite/`: `conftest.py` + `test_01_supplier_scoring.py` … `test_14_clock.py` (14 files)

### Self-audit checks run

1. **Tag uniqueness** — every one of 107 test functions has exactly one `Design:` docstring line (AST-verified).
2. **Tag-to-instance resolution** — 107/107 tags resolve to a real instance with matching rule_id/section; 0 dual/unknown/malformed tags.
3. **Coverage** — 20/20 queue-A instances with ≥2 tests; 67/68 queue-B non-stub instances with ≥1 (the 1 gap is the deliberate skip above).
4. **PRD verbatim citations (C1)** — a distinctive ≥40-char quoted span from every docstring survives a whitespace-normalized literal grep of PRD.md: 107/107 pass (6 initially failed due to ellipsis compression; fixed by quoting contiguous sentences).
5. **Error-ID prose coverage** — all 41 distinct asserted `ApiErrorId`s appear in PRD §2/§3 prose, not only the §5 table.
6. **Style** — all files compile; all 14 test modules import cleanly against the installed `prd_bench_local_runner` framework; no `pytest.mark.skip/skipif/xfail`; no scaffold references in comments/docstrings.

## Step 6: Generate Implementation — 2026-08-13T03:56:00.000Z

Implementation complete and verified. Summary below.

## File list — `tasks/task_1371_medical_device_contract_manufacturing/workspace/implementation/`

- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, envelope error handlers (ApiError, 404, 405, 500)
- `store.py` — in-memory `DB` dicts keyed by id, logical clock (starts exactly `2026-08-01T00:00:00Z`, never wall-clock), `new_entity` (id/created_at/updated_at/version=1), `bump` (version+1, updated_at refresh — used for direct writes and every cascade mutation)
- `timeutil.py` — ISO-8601 parse (second precision, UTC-normalized), strict-UTC parse for the clock endpoint, 3-fractional-digit `Z` formatting, calendar `add_months` (day preserved, month-end clamped, time-of-day preserved)
- `errors.py`, `envelope.py` — `ApiError(error_id, http_status)`, exact `{meta:{api_request_id, api_request_timestamp}, response_type, data}` envelope; pagination fields `limit/offset/total_count/has_more` in `meta` for lists only
- `auth.py` — `X-User-ID`/`X-User-Role` extraction, six exact role names
- `validate.py` — step-3 shape validators (strict types: bool-not-int, enums, positive ints, datetimes) and step-4 existence
- `domain.py` — serialization, filters, all calculations and cascades
- `routes_dmrs.py`, `routes_lines.py`, `routes_suppliers.py` (suppliers + agreements + parts + SCNs + audits), `routes_protocols.py`, `routes_studies.py`, `routes_lots.py` (lots + components + labels), `routes_quality.py` (NCRs + complaints + CAPAs + field actions), `routes_clock.py`

## Coverage

- **Entities (16)**: all scaffold entities with exact field names, sources (input/computed/system), and defaults. No seeding anywhere — `app.py` boots with an empty store.
- **State machines**: all 13 machines implemented including parallel `disposition_status` × `hold_status` on DeviceLot (cascade holds are no-ops when already ON_HOLD, reason retained), cyclic machines (protocol revalidation generation bump + phase-id clearing, CAPA INEFFECTIVE loop with `effectiveness_cycles`), terminal lockdowns, and all four system revalidation triggers (TIME_EXPIRY, SUPPLIER_CHANGE, CAPA_PROCESS_CHANGE, STUDY_FAILURE).
- **Calculations (6)**: `lot_expiry` (dual provisional/final variant, ceil-half capped 12 / confirmed capped 60, calendar months); `supplier_quality_score` (current vs finalized variants recomputed from source NCRs+audits per the exact linkage formula, severity 5/15/30, audit 2/8, floor 0, tier 90/70, auto-suspend < 50 with full cascade); `sterile_sample_qty` (maturity <3 → 100%, tier table 25/150/1200/10000, single integer ceil after ×1.5 for critical parts); `complaint_rate_per_100k` (pinned evaluation order: mutations → RELEASED-only denominator → confirmed numerator → Decimal ROUND_HALF_UP 4dp → 5.0 flag); `audit_due_schedule` (tier intervals 24/12/6, never-audited → created+12mo, inclusive overdue comparison, DISQUALIFIED exempt); `udi_check_digit` (GS1, rightmost of the 13 digits weight 3 alternating — PRD wording followed where it overrides the scaffold formula).
- **OCC**: only the two declared endpoints — `POST /api/suppliers/{id}/quality-agreements` (`expected_supplier_version`) and `POST /api/device-master-records/{id}/revisions` (`expected_dmr_version`) — checked at pipeline step 5 (after shape/existence, before SoD/state), `ERR_STALE_VERSION` 412; successful creation bumps the parent's `version` (and `updated_at`) as a side effect. No other endpoint accepts a version field.
- **Validation order**: the 12-step pipeline is implemented per route in pinned order — headers (400) → role (403) → body shape (400, incl. UDI check digit and NCR requires lot-or-part) → path ids left-to-right then body FKs (404) → OCC (412) → segregation of duties (403, checked *before* state-shape: DMR approve vs author, phase approve vs executor, NCR close vs initiator, CAPA verify vs initiator) → state shape (409) → named preconditions (409) → safety gates in listed order (sterility → protocol → open NCRs → printed label → DMR approved; complaint intake) → temporal windows (409; agreement window checked before supplier-disqualified per priority 10 < 12) → cross-reference (422) → uniqueness/capacity (409, in listed order: duplicate → insufficient qty → part-not-qualified).
- **Logical clock**: `POST /api/_clock/set_current_utc` (QMSAdmin only), monotonic (equal allowed, backwards or non-UTC/non-ISO → `ERR_CLOCK_REGRESSION`), fires exactly the two sweeps in order: agreement expiry (with last-ACTIVE → supplier-suspension cascade) then protocol TIME_EXPIRY revalidation (with lot-hold cascade).

## start.sh contract

Confirmed: reads `$PORT` (default 10000 in `app.py`), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`, and guards the dependency install with `python3 -c "import flask"` so per-test reboots skip pip.

## Verification

Two smoke suites (run against fresh boots) pass 100%: ~110 assertions covering auth/RBAC, every entity CRUD+action, SoD pairs, OCC stale/success paths, all six calculations with concrete numbers, suspension/disqualification cascades, NCR penalty apply/finalize/reverse, SCN-MAJOR-critical revalidation cascade, study pass/fail cascades, CAPA process-change cascade, field-action recall scoping with label voiding, clock sweeps, hold resolution rules, and envelope/pagination shape. Fresh-boot isolation confirmed: a second `start.sh` instance starts with empty collections and the clock at the default instant.

## Step 7: Run Tests and Iterate — 2026-08-13T04:10:00.000Z

All 8 rounds pass 107/107. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep: 103/107 in all 8 rounds, 4 stable failures; post-fix sweep: 107/107 in all 8 rounds).

- **Tests deleted:** None. All 4 failing tests assert rules verbatim-covered by PRD (label active-conflict and print-gate per §3.6; CAPA process-change revalidation cascade per §3.7 and cascade lot-scope per §3.3). The failures were pure test-code plumbing bugs, not assertion/PRD mismatches.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/test_suite/test_07_labels.py` — added `approve_label` to the `test_helpers` import list; `test_label_second_active_conflict` and `test_label_print_requires_completed_lot` called the bare helper `approve_label(...)` (which exists in `test_helpers/fixtures.py`) without importing it → `NameError`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/test_suite/test_11_complaints_capa_field_actions.py` — `TestCapaProcessChangeRevalidationChain._setup(self)` referenced the `api` fixture as a bare name without receiving it; changed signature to `_setup(self, api)` and updated both call sites (`test_implement_flips_validated_protocol_to_revalidation`, `test_revalidation_cascade_leaves_released_lots_untouched`) to pass the injected fixture → fixes `NameError: name 'api' is not defined`.

- **Fixes applied to `implementation/`:** None — the implementation was already fully PRD-faithful; every failure was a test-side NameError.

**Final state:** 8/8 parallel rounds at 107 passed / 107 total / 0 failed under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-13T04:25:00.000Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/workspace/PRD_FINALIZED.md` as an exact, byte-identical copy of `PRD.md` (verified with `diff -q`).

## Summary

**Line counts / %-delta:** PRD.md = 438 lines; PRD_FINALIZED.md = 438 lines; delta = 0 lines, 0.0%.

**Changes:** None — zero edits were warranted.

### Per-item reasoning (why each step_7_diff item required no PRD change)

1. **`test_suite/test_07_labels.py` — added `approve_label` to imports (NameError fix).**
   This is a pure test-plumbing bug: `approve_label` already existed in `test_helpers/fixtures.py:328` and was exported; the test file simply failed to import it. No behavior was deleted or weakened. The two tests that use it assert rules the PRD pins verbatim:
   - `test_label_second_active_conflict` asserts `ERR_ACTIVE_LABEL_EXISTS` when a second label of the same lot is approved while one is `APPROVED`/`PRINTED` — PRD §3.6 (line 257) states exactly this, and `implementation/routes_lots.py:367-370` implements exactly this check.
   - `test_label_print_requires_completed_lot` asserts printing a non-`COMPLETED` lot's label fails with `ERR_LOT_NOT_COMPLETED` and leaves the label `APPROVED` with `printed_at` null — PRD §3.6 (line 257) states exactly this, and `implementation/routes_lots.py:378-390` implements exactly this gate.
   PRD and implementation agree; the failure was only the missing import. No PRD silence, no mismatch → no edit.

2. **`test_suite/test_11_complaints_capa_field_actions.py` — `_setup(self)` → `_setup(self, api)` fixture-signature fix (NameError fix).**
   Again pure plumbing: the helper referenced the `api` fixture without receiving it. The two tests it serves assert rules the PRD pins verbatim:
   - `test_implement_flips_validated_protocol_to_revalidation` asserts the CAPA `process_change` cascade (`IMPLEMENTING`, protocol → `REVALIDATION_REQUIRED` with `CAPA_PROCESS_CHANGE`, in-flight lots held `REVALIDATION`) — PRD §3.7 (line 279) states exactly this; `implementation/routes_quality.py:408-420` plus `domain.py:150-156` (`revalidate_protocol`) and `domain.py:127-133` (`hold_inflight_lots_of_protocol`) implement exactly this.
   - `test_revalidation_cascade_leaves_released_lots_untouched` asserts the cascade's lot scope is limited to `IN_PRODUCTION`/`COMPLETED` lots (a `RELEASED` lot stays `RELEASED`/`CLEAR`) — PRD §3.3 (line 213) states exactly this scope, and `domain.py:127-133` filters on exactly those two disposition statuses.
   PRD and implementation agree; the failure was only the fixture signature. No PRD silence, no mismatch → no edit.

3. **No test deletions, no `test_helpers/` fixes, no `implementation/` fixes** — nothing further to trace.

### Pre-edit search log
Zero edits were committed, so no per-edit (a)/(b)/(c) entries exist. The verification searches above (PRD grep for all four asserted rule texts; implementation reads of `routes_lots.py` label approve/print, `routes_quality.py` CAPA implement, `domain.py` revalidation/hold helpers) confirmed every behavior the Step 7 fixes touched is already uniquely determined by existing PRD prose and faithfully implemented, so the copy stands unmodified.

## Step 9: PRD Completeness Scan — 2026-08-13T04:40:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1371_medical_device_contract_manufacturing/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`. No sections added/removed; all changes are inline inserts/revisions. Every endpoint, state transition, formula, validation gate, error, default, side effect, response shape, and ordering rule in `implementation/` was walked and cross-classified against the PRD.

**Size**: PRD_FINALIZED.md 438 lines / 66,912 chars → PRD_COMPLETED.md 440 lines / 69,460 chars (delta +2 lines, +2,548 chars).

**Counts**: 16 ambiguity-pins, 2 mismatch-revisions.

**Changes**:
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped to nearest bound, unparseable values fall back to defaults — `implementation/envelope.py:40-59`
- §2.3 — insert — ambiguity — same-timestamp list ordering tie-broken by creation sequence — `implementation/domain.py:64`
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — `implementation/store.py:62`
- §2.5 — revise — ambiguity — clock set requires explicitly-UTC ISO 8601 (`Z` or `+00:00`; naive/other offsets rejected); setting to exactly the current value succeeds — `implementation/timeutil.py:29-47`, `implementation/routes_clock.py:21-25`
- §2.9 — revise — mismatch — NCR lot-genealogy attribution applies whenever `lot_id` is set (not only when `supplier_part_id` is absent); a report with both references can count against several suppliers — `implementation/domain.py:166-183`
- §2.10 — insert — ambiguity — named precondition gates not enumerated in steps 8–12 (`ERR_NO_COMPONENTS_RECORDED`, `ERR_LOTS_IN_FLIGHT`, `ERR_PROTOCOLS_IN_FLIGHT`, `ERR_NO_ACTIVE_QUALITY_AGREEMENT`, `ERR_SCORE_BELOW_REINSTATE_THRESHOLD`, `ERR_SUPPLIER_NOT_CLEAR`, `ERR_SCN_PENDING`, `ERR_DMR_NOT_STERILE`, `ERR_CAPA_NOT_CLOSED`, `ERR_SOURCE_NOT_CLOSED`, SCRAP-disposition lot-state gate) evaluated after step 7, before step 12, in workflow-prose order — verified across `routes_dmrs.py:106-115`, `routes_suppliers.py:79-83,104-112,302-311`, `routes_studies.py:24-35`, `routes_lots.py:96-100`, `routes_quality.py:303-309,444-453,560-566`
- §3.2 — revise — ambiguity — `result_months_confirmed` must be a strictly positive integer when `passed` is true — `implementation/routes_studies.py:75`
- §3.4 — insert — ambiguity — audit-notice check applies only when the supplier has an `ACTIVE` agreement — `implementation/routes_suppliers.py:436-440`
- §3.4 — insert — ambiguity — newly scheduled audit starts with `findings_count`/`major_findings_count` null, `penalty_points` 0, `completed_at` null — `implementation/routes_suppliers.py:441-450`
- §3.4 — revise — mismatch — audit penalty is twice `findings_count` (not "twice the minor findings") plus eight times `major_findings_count`, matching §2.9 — `implementation/routes_suppliers.py:479`, `implementation/domain.py:201`
- §3.5 — insert — ambiguity — receipts accepted regardless of part status — `implementation/routes_suppliers.py:284-294`
- §3.5 — insert — ambiguity — change-notice check applies only when the supplier has an `ACTIVE` agreement — `implementation/routes_suppliers.py:333-337`
- §3.5 — insert — ambiguity — a `MAJOR` acceptance without `supplier_part_id` scope has no downstream cascade — `implementation/routes_suppliers.py:387`
- §3.6 — insert — ambiguity — new lot starts with `sample_qty` 0 and `releasable_qty` equal to `quantity` — `implementation/routes_lots.py:66-67`
- §3.6 — insert — ambiguity — `udi_pi` computed once at label creation (not rewritten on later expiry recomputation); label starts with `printed_at` null and `void_reason` `NONE` — `implementation/routes_lots.py:320,327-328`
- §3.6 — insert — ambiguity — label approval against a lot that left `IN_PRODUCTION`/`COMPLETED` fails with `ERR_INVALID_STATE_TRANSITION` — `implementation/routes_lots.py:354-355`
- §3.7 — insert — ambiguity — `SCRAP` disposition against a lot no longer in flight fails with `ERR_INVALID_STATE_TRANSITION` — `implementation/routes_quality.py:115-117`
- §3.7 — insert — ambiguity — auto-created CAPA carries a server-generated unique `capa_code`; the `confirmed` list filter accepts case-insensitive `true`/`false` and matches nothing otherwise — `implementation/routes_quality.py:261`, `implementation/domain.py:51-58`
