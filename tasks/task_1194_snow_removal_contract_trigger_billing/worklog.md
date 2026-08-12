# Worklog — task_1194_snow_removal_contract_trigger_billing

## Step 1: Create task directory — 2026-08-11T00:00:00.000Z

Pre-assigned output folder `tasks/task_1194_snow_removal_contract_trigger_billing` with `workspace/` subdirectory already existed; auto-index scan skipped per instructions. Difficulty parameter: "generate task hard than expert level!".

## Step 2: Generate Scaffold — 2026-08-11T18:31:00.000Z

Done. All three artifacts generated, lint-clean, for task 1194 (Snow Removal Contract & Trigger Billing), calibrated harder than expert level.

**Files on disk (verified via ls -la):**
- `SCAFFOLD.yaml` (116 KB) — §1.0–§1.7 only; neither design key present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (90 KB) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (186 KB) — single top-level key `scaffold_corner_design`

**Counts (verbatim from lint + parse):**
- Entities: **16** (Client, Site, Contract, ContractSite, ContractAmendment, StormEvent, WeatherObservation [append-only, common_fields:false], ServiceVisit, MaterialApplication, ServicePhoto, Invoice, Dispute, SlipFallClaim, Subcontractor, CoverageAssignment, SeasonalTrueUp)
- Endpoints: **85** (flat topology, body-FK creation; includes `POST /_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` default)
- State machines: **12**, including a StormEvent verification cycle (REPORTED→VERIFIED→CHALLENGED→VERIFIED), dual independent state dimensions on ServiceVisit (execution × billing), Dispute evidence loop, Contract ACTIVE⇄SUSPENDED cycle
- Calculations: **15** (3 dual-variant: billing preview provisional/final, material actual-vs-area-normative, true-up projected/final; combinatorial formulas in all three modes: tiered+night-premium hourly charge, pinned round-per-line-then-sum material costing, pinned evaluation-order true-up settlement)
- Validations: **21** ordered priorities; Errors: **42**; Roles: **6** (segregation_of_duties model; Subcontractor/ClientContact entity-backed); Concurrency rules: **2** (OCC on Contract.version for amendment and true-up create-with-supersede)
- §1.8 instances: **18** (9 rules × 2, all with structured `setup_api_calls`/`trigger`/`assert`, pre-computed literal expectations such as hourly charges 22500/9000, rounding-order 111-vs-110, true-up balance 30000)
- §1.9 instances: **79 rows = 59 active + 20 `excluded_because` stubs** (all 42 error codes triggerable; all FKs reverse-reachable)
- Lint: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1147 calls scanned)
- Additional audits passed: placeholder closure (zero unbound `${var}`), 97 instance names unique across both design files, forbidden race vocabulary scan clean, fixed-envelope block verbatim.

**Fixes applied during self-review:** added `renewed_to_contract_id?` filter for FK reverse-reachability; added PARTIALLY_PAID/PARTIALLY_CREDITED→VOIDED transitions so ERR_INVOICE_HAS_PAYMENTS (fiscal, priority 21) is reachable instead of being shadowed by the priority-5 state check; removed unproducible SeasonalTrueUp DISCARDED enum value (enum closure); fixed one corner recipe where a nonexistent storm-event UUID would have triggered priority-3 ERR_NOT_FOUND before the priority-13 type check under test; corrected a claim incident timestamp to fall inside the storm window so the bundle scores (85 STANDARD / 70 STRICT) hold.

## Step 3: Copy INSTRUCTION.md — 2026-08-11T18:32:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T18:45:00.000Z

PRD generation complete and verified. `workspace/PRD.md` exists on disk — 359 lines.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC (6 roles, identity prose for each: 4 opaque, 2 entity-backed), 2.2 API Response Structure (verbatim fixed block — byte-identical check PASS), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Logical Clock (fixed `2026-05-01T00:00:00Z` startup default, `to_iso8601`/`current_utc`), 2.5 Common Resource Properties (UUID `id`, 3-fractional-digit timestamps, `version`; WeatherObservation carries only `id`/`created_at`), 2.6 Monetary/Measurement Precision (integer cents, round-half-up staging, per-line/per-tier/per-site rounding, floors), 2.7 OCC (`expected_contract_version` on amendment and true-up creation, `ERR_STALE_CONTRACT_VERSION`/412, no race framing), 2.8 Order of Validation (all 21 priority tiers in order with error IDs), 2.9 Cascades & Accumulators, 2.10 Flat Addressing / left-to-right identifier resolution
- §3 Business Logic (9 subsections, season-timeline grouping): 3.1 Onboarding, 3.2 Contract Lifecycle, 3.3 Storm Events & Verification, 3.4 Subcontractor Coverage & Failure, 3.5 Visit Execution, 3.6 Materials & Photos, 3.7 Billing/Invoicing/Payments, 3.8 Disputes & Slip-and-Fall Claims, 3.9 Seasonal True-Up
- §4 Endpoint Definitions (4-column table, all 85 endpoints with authorized roles)
- §5 Error Code Catalogue (2-column table, all 42 error IDs)

**Hard contract reports**:
- Contract 1 (Field-Name Coverage): entities[].fields 133/133 present, 0 missing; endpoints[].request_body 81/81 present, 0 missing; query_params 0/0; path_params 1/1. **Status: PASS** (verified programmatically against SCAFFOLD.yaml with fenced-code-aware token extraction)
- Contract 2 (Rule Coverage): validations priority ordering expressed as the 21-tier cascade in §2.8 with explicit earliest-tier-wins semantics; both `concurrency_rules` expressed with write endpoint + `expected_contract_version` + exact error/status; all 12 state machines' transitions, preconditions, and side effects expressed (including L1–L3 verification/failure cascades, challenge revert, close-sweep MISSED marking, visit-void compensation, invoice issue/void money movement, three symmetric dispute outcomes, three symmetric invoice-void branches); all 15 calculations in reconstruction-grade prose (quorum/latest-observation verification, PROVISIONAL/FINAL projection variants, inclusive trigger threshold, frozen per-push snapshot, chronological hourly tiering with per-tier rounding and last-rounding night premium, round-per-line-then-sum materials, ACTUAL-vs-AREA_NORMATIVE settlement with 0.0023/0.0015/0.0040 normative rates, pinned 6-step true-up order with 20% credit cap floor, half-open PERIOD invoice filter, strict-greater SLA verdict, 90-minute buffer with equality legal, guarded reliability floor, STANDARD 15/25/20/20/20 vs STRICT 30/40/10/10/10 documentation weights, deterministic backup selector); defaults (2.00 in, 2,400 min, 0.25, 15000, true, 25/60/35) and constants (48 h challenge, 6 h photo window and observation grace, 2 h backup grace, 60-day post-season billing, score floor 60, suspend at <70 with ≥3 assignments) embedded with unit conversions. **Status: PASS**
- Contract 3 (§3 Path Purity): 757 backtick tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. **Status: PASS**

**Coverage notes**: all 42 error IDs appear in §2/§3 prose (each trigger condition stated near its workflow); all 6 role names exact; all enum/state values appear as exact UPPERCASE strings; no fuzzy/approximating words and no operator pseudocode (verified by scan); §4 table is 4-column minimal, §5 table is 2-column; the withheld design index files were never opened. One gap found and fixed during verification: the contract-`ACTIVE` gate for photo upload and visit completion (`ERR_CONTRACT_NOT_ACTIVE` per validation tier 20) was added to §3.5/§3.6.

## Step 5: Generate Unit Tests — 2026-08-11T19:20:00.000Z

**Files written**

- `test_helpers/` — 9 files: `__init__.py`, `types.py`, `api_client.py` (one method per PRD §4 endpoint, `GenericApiClient` subclass), `api_errors.py` (40 error IDs + HTTP map, registered via `set_error_http_status_map`), `assertions.py` (per-entity + invariant checkers; `WeatherObservation` asserts absence of `updated_at`/`version`), `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_client_headers`/`make_subcontractor_headers` entity-backed builders + custom-id opaque builders for segregation-of-duties tests), `fixtures.py` (5-tier composite helpers: clock, hierarchy builders, storm/observation/verify, visit lifecycle, invoices, subcontractor/coverage, expire).
- `test_suite/` — `conftest.py` + 11 test files (`test_01_onboarding_defaults_and_schema.py` … `test_11_overlap_occ_and_terminal.py`).

**Test counts per queue** (99 total, all with exactly one terminal `Design:` docstring line, no orphans, no skip/xfail)

- Queue A (Difficulty): 38 tests — all 18/18 instances covered with ≥2 tests each.
- Queue B (Corner): 61 tests — 58/59 non-stub instances covered with ≥1 test each; 20 `excluded_because:` stubs not translated (all cross-references verified to resolve to real §1.8 instances).

**Instances skipped (with reason)** — 1:

- `Corner/endpoints/route_plan_orders_by_priority_sequence` — the PRD names only `route_order` on the route-plan entry ("each entry is assigned a `route_order` counting upward from 1"); no verbatim PRD sentence pins the entry→visit binding field (e.g. `visit_id`), so the instance's load-bearing assertion `data[0].visit_id == vB` fails the unique-derivability condition (two PRD-only readers could pick different entry field names). Gap left as a gap.

**PRD-first relaxations applied (not skips)** — 2: in `test_issue_voided_invoice_state_tier_beats_fiscal_tier` and `test_terminal_lockdown_paid_invoice_and_rejected_photo` (invoice half), the asserted error uses `validate_error_is_one_of([ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` because PRD §2.8 places both in the fifth tier and never declares Invoice `VOIDED`/`PAID` explicitly terminal; the tier-ordering claim itself (state tier 5 pre-empts fiscal tier 21) is verbatim-covered and asserted.

**Verification results**

- `ls` confirms all 21 files on disk (9 helpers + 12 suite files incl. conftest).
- `python -m py_compile` on every file: ALL OK.
- `pytest --collect-only`: 99 tests collected, 0 import errors.
- Coverage audit script: queue A 18/18 ≥2 tests, queue B 58/59 ≥1 test, 0 orphan tags, 20 stubs with all `excluded_because` references resolving.
- Citation audit: every test's docstring contains at least one ≥8-word run that literally greps against `workspace/PRD.md`; every docstring ends with exactly one `Design:` line resolving to a real instance in the source YAMLs.

## Step 6: Generate Implementation — 2026-08-11T19:20:00.000Z

**Files written** (all under `workspace/implementation/`):

- `start.sh` — executable foreground launcher, guards pip install, uses `exec python3 app.py`
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry point, registers 17 blueprints, error handlers for ApiError/404/405/500
- `db.py` — In-memory store (16 Store instances), logical clock (default 2026-05-01T00:00:00Z), UUID generation, ISO 8601 helpers
- `errors.py` — ApiError exception class + 40 error ID constants matching scaffold §1.6
- `response.py` — Envelope helpers: `success_object` (meta/response_type/data), `success_list` (with pagination meta), `error_response`
- `middleware.py` — Auth header validation (X-User-ID, X-User-Role), role checking, pagination parsing, JSON body parsing
- `services/__init__.py`, `services/helpers.py` — Accumulator recomputation, billing evaluation, hourly tiered pricing, material cost (round-per-line), season/coverage overlap, reliability score, claim scoring
- `routes/__init__.py` + 17 route modules: `clock.py`, `clients.py`, `sites.py`, `contracts.py`, `contract_sites.py`, `amendments.py`, `storm_events.py`, `observations.py`, `visits.py`, `materials.py`, `photos.py`, `invoices.py`, `disputes.py`, `claims.py`, `subcontractors.py`, `coverage.py`, `true_ups.py`

**Route count matched vs scaffold**: 85/85 — PERFECT MATCH (no missing, no extra)

**py_compile result**: ALL COMPILED OK (all 20 Python files)

**start.sh executable**: Yes (`-rwxrwxr-x`)

**Smoke test result**: PASS
- `POST /_clock/set_current_utc` returned 200 with correct logical clock
- `POST /clients` returned 201 with created client (UUID, version=1, credit_exposure_cents=0)
- `POST /clients` without auth headers returned 401 with `ERR_UNAUTHENTICATED`

**Storage**: In-memory only (Python dicts via `Store` class). No SQLite, no JSON files, no /tmp cache. No seeding at startup — all stores start empty.

## Step 7: Test-Fix Iteration — 2026-08-11T20:02:00.000Z

**Iteration 1 sweep**: 94/99 in all 8 rounds — 5 deterministic failures.

**Diagnoses (PRD-first protocol)**:

1. `test_hourly_day_visit_bears_tier2_minutes_chronologically` — IMPLEMENTATION BUG. PRD §3.7: "tier allocation is chronological across the season, ordered by `actual_start_at` and then by `created_at`". The `verify_storm_event` cascade evaluated COMPLETED visits in insertion order, so a later-created/earlier-started visit billed after a later-starting one got the full tier-1 headroom. Fix in `implementation/routes/storm_events.py` (`verify_storm_event`): sort the cascade by (`actual_start_at`, `created_at`) before `evaluate_visit_billing`.
2. `test_draft_invoice_reconciles_when_second_visit_confirms` — TEST BUG. Second visit scheduled 11:00-11:30 left a 60-min gap after the first visit (09:00-10:00), violating PRD §3.5's 90-minute same-site buffer; `ERR_VISIT_GAP_CONFLICT` was the correct rejection. Fixed `test_suite/test_06_invoices_and_payments.py`: v2 moved to 11:30-12:00 (exactly 90 min, legal per PRD).
3. `test_capability_mismatch_wins_over_overlap_on_dual_failure` + `test_capability_mismatch_isolated_without_overlap` — TEST BUG in shared fixture `_setup_capability_overlap_scenario` (`test_suite/test_08_coverage_and_backup.py`): event window [00:00,08:00) did not overlap the tested coverage windows [10:00,18:00) / [14:00,18:00), tripping PRD §3.4's "must overlap the event's window" (tier-9 `ERR_INVALID_REQUEST`) before tier-11 capability. Fix: widened the fixture's event window to [00:00,23:00).
4. `test_duplicate_coverage_triple_rejected` — TEST BUG: second coverage window [12:00,18:00) did not overlap the default event window [00:00,08:00), same tier-9 pre-emption. Fix: event window widened to [00:00,23:00); the two coverage windows remain non-overlapping (back-to-back), preserving the test's intent.

**No test deletions** — all 5 asserted rules are verbatim PRD-covered and uniquely derivable.

**Iteration 2 sweep**: all 5 fixes green, but each of the 8 rounds showed exactly 1 setup-phase "server could not be restarted" error (or 1 connection reset), traced to host contention from a concurrently-running sibling pipeline (task_1199). No assertion failures.

**Iteration 3 sweep (host quiet)**: 8/8 rounds × 99/99 passed, 0 failed, 0 errors. STABLE — exit condition met.

## Step 7: Run Tests and Iterate — 2026-08-11T20:02:00.000Z

**Exit condition met: 8/8 parallel rounds × 99/99 passed, 0 failed, 0 errors.**

- **Iterations run:** 3 sweeps (24 rounds total). Sweep 1: 94/99 × 8 (5 deterministic failures). Sweep 2: fixes green but 1 transient setup-phase server-restart error per round, traced to host contention from a concurrently running sibling pipeline (task_1199); zero assertion failures. Sweep 3 (host quiet): 8/8 clean.

- **Tests deleted:** none — all 5 failing tests asserted rules verbatim-covered and uniquely derivable in PRD.md.

- **`test_helpers/` fixes:** none (the buggy fixture code lived inline in test_suite files).

- **`test_suite/` fixes:**
  - `test_suite/test_06_invoices_and_payments.py` (`test_draft_invoice_reconciles_when_second_visit_confirms`) — second visit rescheduled 11:00–11:30 → 11:30–12:00; the original 60-minute gap violated PRD §3.5's 90-minute same-site buffer, and the implementation's `ERR_VISIT_GAP_CONFLICT` was the correct rejection.
  - `test_suite/test_08_coverage_and_backup.py` (`_setup_capability_overlap_scenario`, fixing both capability-priority tests; and `test_duplicate_coverage_triple_rejected`) — event windows widened to end at 23:00 so the tested coverage windows actually overlap the event window as PRD §3.4 requires ("must overlap the event's window"); previously the tier-9 `ERR_INVALID_REQUEST` window check pre-empted the tier-11/12 errors under test.

- **`implementation/` fixes:**
  - `workspace/implementation/routes/storm_events.py` (`verify_storm_event`) — the verification cascade now sorts COMPLETED visits by (`actual_start_at`, `created_at`) before `evaluate_visit_billing`, realizing PRD §3.7's "tier allocation is chronological across the season, ordered by `actual_start_at` and then by `created_at` — never by completion order." Previously insertion order governed, so a later-created but earlier-starting visit was billed after the later-starting one, granting it full tier-1 headroom (12000c instead of 9000c).

## Step 8: Finalize PRD — 2026-08-11T20:10:00.000Z

PRD_FINALIZED.md is written at `workspace/PRD_FINALIZED.md` as an exact copy of PRD.md (verified byte-identical via `diff`).

**Line counts / %-delta:** PRD.md = 359 lines; PRD_FINALIZED.md = 359 lines; delta = 0 lines, 0.0%.

**No edits were needed.** All three `<step_7_diff>` items trace to behavior the PRD already determines. Per the instructions, PRD_FINALIZED.md was produced as an exact copy.

### Per-item verification log (pre-edit search concluding "no edit")

**Item 1 — test_06_invoices_and_payments.py (second visit rescheduled 11:30–12:00)**
- (a) Subject: same-site 90-minute re-service buffer (`ERR_VISIT_GAP_CONFLICT`), equality legality.
- (b) Paths enumerated: PRD §3.5 (line 160: "at least ninety minutes after ... or ... at least ninety minutes before ... a gap of exactly ninety minutes is legal on either side"); impl `routes/visits.py:85-98` (`REAPPLY_GAP = timedelta(minutes=90)`; conflict unless `new.start >= ex.end + 90min OR new.end + 90min <= ex.start` — equality legal on both sides, matching PRD verbatim).
- (c) No wording adjustment — step_7_diff itself labels this a pure test-schedule fix; PRD already pins the buffer with equality legal. No PRD silence or mismatch.

**Item 2 — test_08_coverage_and_backup.py (coverage fixture windows widened to 23:00)**
- (a) Subject: coverage window must overlap the storm event's window (tier-9 `ERR_INVALID_REQUEST` check).
- (b) Paths enumerated: PRD §3.4 (line 150: "a half-open coverage window from `coverage_start` to `coverage_end` — the end exclusive, the end strictly later than the start — which must overlap the event's window"); impl `routes/coverage.py:48-60` (well-formedness check `coverage_end > coverage_start`, then event-window overlap check raising `ERR_INVALID_REQUEST`); also coverage.py:78-79 and :160-161 (`check_coverage_overlap` at creation and activation, matching PRD §3.4's "this overlap check runs both at creation and again at activation").
- (c) No wording adjustment — pure fixture-window fix; PRD already pins the overlap requirement and the tier-9 schema-sanity classification (line 98: "well-formed windows with end after start ... failing as `ERR_INVALID_REQUEST`").

**Item 3 — implementation/routes/storm_events.py verify_storm_event cascade sort**
- (a) Subject: chronological tier allocation order for HOURLY visits — (actual_start_at, created_at), never completion/insertion order.
- (b) Paths enumerated: PRD §3.7 (line 184: "tier allocation is chronological across the season, ordered by `actual_start_at` and then by `created_at` — never by completion order. Of the visit's minutes, the portion billed at tier 1 is the headroom remaining under `hourly_tier_threshold_minutes` after accounting for all chronologically earlier billable visits of the contract"); impl storm_events.py:152-165 (post-fix cascade sorts COMPLETED visits by (actual_start_at, created_at) before `evaluate_visit_billing`); services/helpers.py:136-174 `compute_hourly_charge` (prior-minutes accounting compares each billable visit's (actual_start_at, created_at) pairwise against the current visit — already PRD-conformant); visits.py:282-287 (completion path calls `evaluate_visit_billing` for a single visit when the event is already VERIFIED/CLOSED — the same PRD sentence governs); contracts.py:9 (imports `evaluate_visit_billing`; no conflicting ordering there).
- (c) No wording adjustment — this was an implementation bug fix bringing impl INTO alignment with the existing PRD sentence, which already exists verbatim and fully determines the fixed behavior across all enumerated callsites.

No new sections, no invented behavior, no prose changes.

## Step 9: Complete PRD — 2026-08-11T20:35:00.000Z

All edits verified in place (the earlier 36-vs-37 was a shell pipeline artifact; the explicit MISSING scan found nothing). Work complete.

**Deliverable:** `workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md = 359 lines / 67,040 chars → PRD_COMPLETED.md = 359 lines / 71,893 chars. Char delta **+4,853**; line count unchanged (all changes are in-paragraph inserts/revisions; no new sections).

**Counts:** 30 ambiguity-pins (inserts), 6 mismatch-revisions — 25 Edit operations touching 25 paragraphs.

### Mismatch-revisions (PRD described behavior impl does not exhibit)
- §3.2 — revise — mismatch — renewal payload now **must** carry `season_start`/`season_end` (PRD said "may carry"); missing → `ERR_INVALID_REQUEST`; also pins that unlisted terms (tier threshold, night premium, photo flag, material rates) copy without override — implementation/routes/contracts.py:271-305
- §3.3 — revise — mismatch — verification cascade L1 re-evaluates every COMPLETED visit **unconditionally, whatever billing_status it holds** (PRD said "moving from PENDING"; impl overwrites even INVOICED/DISPUTED visits) — implementation/services/helpers.py:177-217, implementation/routes/storm_events.py:155-166
- §3.5 — revise — mismatch — voiding a visit leaves `season_sla_miss_count` **unchanged** (voided visit retains `sla_miss`; PRD said "subtracts one") — implementation/routes/visits.py:319-335, implementation/services/helpers.py:50
- §3.7 — revise — mismatch — invoice issue advances contract `version` **twice** (accumulator recompute + issuance), not "by one" — implementation/routes/invoices.py:204-206
- §3.7 — revise — mismatch — invoice void advances contract `version` **twice**, not "by one" — implementation/routes/invoices.py:253-255
- §3.9 — revise — mismatch — true-up creation check sequence pinned as type-gate → EXPIRED-gate → OCC (impl checks OCC last, contrary to §2.8's default tier positions) — implementation/routes/true_ups.py:31-43

### Ambiguity-pins (PRD silent; pinned to impl)
- §2.1 — insert — ambiguity — entity-backed list endpoints silently filter rather than 403 — implementation/routes/contracts.py:166-167 et al.
- §2.3 — insert — ambiguity — out-of-range/malformed `limit`/`offset` are clamped, never rejected — implementation/middleware.py:36-49
- §2.3 — insert — ambiguity — equal `created_at` ties retain insertion order (stable sort) — implementation/routes/clients.py:56 et al.
- §2.3 — insert — ambiguity — `has_more` = `offset + limit < total_count` — implementation/response.py:31
- §2.8 — insert — ambiguity — request-shape checks (unknown fields, required scalars, enums) surface while reading the payload, before identifier resolution; §3 narrative sequences override the default tier order — e.g. implementation/routes/amendments.py:22-38
- §2.8 — insert — ambiguity — `ERR_VERIFICATION_QUORUM` added to the tier-20 cross-entity gate list — implementation/routes/storm_events.py:126
- §3.1 — insert — ambiguity — supplied `prior_contract_id` must resolve, else `ERR_NOT_FOUND` — implementation/routes/contracts.py:84-88
- §3.1 — insert — ambiguity — contract-site `effective_*` values resolve once at link creation, never re-resolved by amendments — implementation/routes/contract_sites.py:54-57
- §3.2 — insert — ambiguity — renewing a non-EXPIRED contract fails `ERR_INVALID_STATE`; season-window violation on renewal fails `ERR_INVALID_REQUEST` — implementation/routes/contracts.py:258-281
- §3.3 — insert — ambiguity — `CLOSED` and `VOIDED` are terminal event states (`ERR_ALREADY_TERMINAL` on further transitions) — implementation/routes/storm_events.py:105-106,240-241
- §3.4 — insert — ambiguity — subcontractor born with `reliability_score` 0 — implementation/routes/subcontractors.py:39
- §3.4 — insert — ambiguity — `active_assignment_count` decrement floored at zero (release and failure) — implementation/routes/coverage.py:210,262
- §3.4 — insert — ambiguity — omitted `failure_reason` records a generic default — implementation/routes/coverage.py:190
- §3.4 — insert — ambiguity — `RELEASED`/`FAILED`/`CANCELLED` terminal coverage states — implementation/routes/coverage.py:145,180,229
- §3.5 — insert — ambiguity — route-plan takes required `contract_id` query param (`ERR_INVALID_REQUEST`/`ERR_NOT_FOUND`), returns paginated entries `{visit_id, contract_site_id, site_id, route_order, execution_status, scheduled_start, scheduled_end}` — implementation/routes/storm_events.py:352-396
- §3.5 — insert — ambiguity — visit terminal execution states: `MISSED`/`CANCELLED`/`VOIDED`, plus `COMPLETED` except for dispatcher void — implementation/routes/visits.py:204,228,298,312,344
- §3.5 — insert — ambiguity — preferred-backup check order (approval → capability → overlap → prior-failure) and prior-failure surfaces `ERR_INVALID_STATE` — implementation/routes/visits.py:358-374
- §3.5 — insert — ambiguity — successful reassign increments backup's `active_assignment_count` — implementation/routes/visits.py:436-440
- §3.7 — insert — ambiguity — invoice line shape `{visit_id, line_type, line_cents}`, emitted in eligible visits' creation order — implementation/services/helpers.py:271-286
- §3.7 — insert — ambiguity — billing-preview response carries `contract_id` — implementation/routes/contracts.py:401-407
- §3.7 — insert — ambiguity — `PAID`/`VOIDED` terminal invoice states — implementation/routes/invoices.py:152,219,268
- §3.8 — insert — ambiguity — dispute-open billing flip is a no-op when the visit is no longer `INVOICED` — implementation/routes/disputes.py:72-75
- §3.8 — insert — ambiguity — request-evidence `note` accepted but not persisted — implementation/routes/disputes.py:158-168
- §3.8 — insert — ambiguity — dispute resolution available only from `EVIDENCE_REVIEW` — implementation/routes/disputes.py:178-179
- §3.8 — insert — ambiguity — claim's linked storm event must match the site's `region_code`, window containment inclusive — implementation/routes/claims.py:189-198
- §3.8 — insert — ambiguity — cross-role close/withdraw outcome fails `ERR_UNAUTHORIZED_ROLE`; `CLOSED`/`WITHDRAWN` terminal — implementation/routes/claims.py:237-260
- §3.9 — insert — ambiguity — true-up preview restricted to `SEASONAL` (`ERR_CONTRACT_TYPE_FORBIDS`), any contract status — implementation/routes/contracts.py:416-417
- §3.9 — insert — ambiguity — `SETTLED`/`SUPERSEDED` terminal true-up states — implementation/routes/true_ups.py:173-174,188-189
- §4 — insert — ambiguity — "List/filter" endpoints accept conjunctive equality query params on the resource's scalar fields (field list named), applied before pagination — e.g. implementation/routes/visits.py:164-186

**Known residual soft spot (accepted, not pinned):** §2.8's absolute tier-order claim vs a few intra-endpoint micro-orderings (e.g. material quantity-positivity before ownership at implementation/routes/materials.py:42-51) — covered generically by the new §2.8 qualification sentence rather than per-endpoint prose.
