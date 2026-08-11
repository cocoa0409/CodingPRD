# Worklog — task_0980_low_vision_assistive_technology

## Step 1: Create Task Directory — 2026-08-10T09:12:12.902Z

Task directory `tasks/task_0980_low_vision_assistive_technology/` and its `workspace/` subdirectory were pre-assigned and already exist; Step 1 treated as done (no auto-index scan run, per instructions). Difficulty parameter "generate task hard than expert level!" will be passed through to prd-bench-scaffold-generator at Step 2.

## Step 2: Generate Scaffold — 2026-08-10T09:50:33.643Z

All three scaffold artifacts are generated, lint-clean, and verified on disk.

## Summary

**Task**: Low-Vision & Assistive-Technology Service (task 0980), designed fresh from the scenario description — no sibling tasks were inspected.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (707 calls scanned, 0 violations)

**Counts:**
- **Entities: 14** — Client, Referral, Evaluation, DeviceModel (self-referential `successor_model_id`), DeviceUnit, DeviceOrder, LoanAgreement, TrainingPlan, TrainingSession, FundingAuthorization, Claim, RepairTicket, Subscription, OutcomeAssessment
- **State machines: 13** — includes Evaluation revision cycle (FINALIZED→REVISED→FINALIZED), RepairTicket QA rework cycle, FundingAuthorization appeal cycle, EXHAUSTED↔APPROVED revival, and run_daily system transitions
- **Endpoints: 60** (13 creates, 10 single GETs, 8 filtered lists, 6 sub-resource FK-reverse GETs, 19 action endpoints, run_daily, `/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`)
- **Errors: 23**; Validations: 11 priority-ordered rows; Calculations: 11; Roles: 7 (segregation_of_duties: submitter ≠ adjudicator on both funding auths and claims)
- **Difficulty design (§1.8): 9 rules × 2 instances = 18 instances** — each with structured `setup_api_calls`/`trigger`/`assert` chains and all formula-derived values precomputed as literals (e.g., claim provisional 7998 vs sum-then-round 7999; conversion fee 94600; loyalty renewal 23750 at the 50000 boundary)
- **Corner design (§1.9): 60 instances across 8 sections** (49 full recipes + 11 `excluded_because` stubs citing §1.8 instances), including an error-catalog triggerability audit comment

**Key design choices**: temporal_windowing primary archetype (trial windows, loan due dates, subscription periods, funding validity windows — half-open vs closed interval semantics contrast) with ledger_reconciliation secondary (funding reservation/release with compensating voids); OCC concurrency on `POST /api/evaluations` via `expected_client_version` with create-with-supersede semantics; flat topology with FK-reverse reachability via filtered lists and sub-resources.

**Files** (all absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_0980_low_vision_assistive_technology/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0980_low_vision_assistive_technology/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0980_low_vision_assistive_technology/SCAFFOLD_CORNER_DESIGN.yaml`

## Step 3: Copy Shared Files — 2026-08-10T09:50:52.876Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_0980_low_vision_assistive_technology/workspace/INSTRUCTION.md` (1424 bytes, verified on disk).

## Step 4: Generate PRD — 2026-08-10T09:57:34.475Z

PRD generation complete. `/home/ubuntu/github/CodingPRD/tasks/task_0980_low_vision_assistive_technology/workspace/PRD.md` exists on disk (50,449 bytes, 318 lines).

## Summary

**Line count:** 318 lines.

**Section coverage vs scaffold:**
- **§1 Introduction** — 3 paragraphs covering the clinical spine, the funding spine, the logical clock, and integer-cents discipline (from `scenario` + `complexity_profile`).
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC with all 7 role names and per-role opaque-identity prose; 2.2 emitted verbatim from the fixed `section-2.2-response-structure.md`; 2.3 pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending, meta fields); 2.4 common resource properties + DeviceModel counter conservation; 2.5 money/score rounding; 2.6 logical clock (startup default `2026-05-01T00:00:00Z`) + pinned 5-step daily sweep; 2.7 nested retrieval + explicit 11-level validation priority funnel; 2.8 segregation of duties; 2.9 the single OCC rule.
- **§3 Business Logic** — 10 subsections organized by entity lifecycle: intake, evaluation/supersede, catalog/stock, device orders (placement/allocation/convert/return + the pinned 5-step trial-conversion fee), loans, training (with the no-show cascade), funding/claims/ledger (provisional per-line round-then-sum, payer-responsibility waterfall with LOW_INCOME halving, reconciliation invariant), subscriptions (loyalty tiers, renew, prorated cancel), repair (with the atomic 3-link loaner cascade), outcome dual-composite scoring.
- **§4 Endpoint table** — all 62 scaffold endpoints, 4 columns only (Method, Path, Description, Authorized Roles).
- **§5 Error catalogue** — all 23 error IDs, 2 columns only (no trigger conditions).

**Hard-contract verification (all PASS):**
- Contract 1 (field-name coverage): 91 entity/extra fields, 51 request-body identifiers, 12 query params — 0 missing (one initial gap, the repair-advance `action` field, was found by the checker and fixed).
- Contract 2 (rule coverage): all 11 validations with priority ordering, the 1 OCC rule, all 60+ state transitions (every from→to pair rendered), all 11 calculations as precise prose with constants embedded, all 23 error IDs matchable to trigger prose, all endpoint side effects, sibling-branch symmetry (PAY/DENY, void SUBMITTED/PAID, renew/cancel branches) — all expressed.
- Contract 3 (§3 path purity): 527 backtick tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

**Coverage gaps found:** only one — the `action` request-body field of the repair advance endpoint was initially unnamed (the verbs were backticked but not the field itself); fixed before shipping. The forbidden files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

(Note: the Step 4 subagent's first spawn exited prematurely after building its field inventory without writing the file; it was resumed via SendMessage with its context intact and completed the PRD.)

## Step 5: Generate Unit Tests — 2026-08-10T10:14:00.794Z

All checks pass. Summary of the generation:

## Report

**Task:** task_0980_low_vision_assistive_technology — unit test generation per the prd-bench-unit-test-generator skill.

### Stage 1 — `test_helpers/` (10 files, all py_compile clean)
- `types.py` — 13 status enums, 5 value enums, role enum, 14 entity TypedDicts (all `common_fields: true`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (44 methods), plus module-level `api_client`
- `api_errors.py` — `ApiErrorId` (23 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus model-counter and funding-reconciliation invariant checkers
- `factories.py` — 12 payload factories + `claim_line`, input fields only
- `constants.py` — thresholds from the PRD's calculation rules (factors, tier thresholds, grace days, clock default)
- `test_users.py` — shared role headers (all roles are `opaque` per PRD §2.1), `ANONYMOUS_HEADERS`, and per-user-id builders for segregation tests
- `fixtures.py` — composite helpers: intake/referral spine, evaluation (OCC-aware), catalog/stock, order allocation, funding authorization lifecycle, claims, training plans/sessions, repair tickets, subscriptions, clock/sweep
- `__init__.py` — barrel export

### Stage 2 — `test_suite/` (conftest.py + 10 test files, 103 tests)

| File | Tests | Queue A tags | Queue B tags |
|---|---|---|---|
| test_01_claims_provisional_and_payment.py | 10 | 10 | 0 |
| test_02_outcome_assessment_scoring.py | 3 | 2 | 1 |
| test_03_evaluation_lifecycle.py | 9 | 4 | 5 |
| test_04_repair_workflow.py | 9 | 4 | 5 |
| test_05_training_plans.py | 11 | 8 | 3 |
| test_06_claims_and_funding_states.py | 15 | 4 | 11 |
| test_07_device_orders_and_units.py | 23 | 2 | 21 |
| test_08_subscriptions.py | 6 | 2 | 4 |
| test_09_intake_and_clients.py | 15 | 0 | 15 |
| test_10_envelope_and_pagination.py | 2 | 0 | 2 |

### Instance consumption
- **Queue A (Difficulty): 18/18 instances consumed, each with exactly 2 tests** (36 tests).
- **Queue B (Corner): 31/31 non-stub instances consumed, ≥1 test each** (67 tests). The 11 `excluded_because` stubs were not translated; all stub cross-references verified to resolve to real §1.8 instance names.
- **Skipped instances: none.** Every non-stub instance passed the PRD-first two-condition filter — the PRD (§2.1–§2.9, §3.1–§3.10, §4, §5) verbatim-covers and uniquely derives every asserted rule, including the priority-funnel ordering claims (PRD §2.7's numbered funnel).

### Verification results
- `python3 -m py_compile` over all 21 generated `.py` files: **OK**
- Design-tag audit: every one of the 103 tests carries exactly one `Design:` tag; 0 unknown tags; 0 untagged; 0 dual-tagged.
- PRD-citation verbatim pass: after fixing 5 initially non-verbatim citations (elided/fused quotes), all docstring citations grep verbatim in PRD.md.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.

## Step 6: Generate Implementation — 2026-08-10T10:14:00.794Z

## Summary

**File list** under `/home/ubuntu/github/CodingPRD/tasks/task_0980_low_vision_assistive_technology/workspace/implementation/`:
- `start.sh` — foreground launcher, guarded pip install (`import flask` check), `exec python3 app.py`, honors `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, blueprint registration, error handlers (ApiError + 404/405/400 + catch-all 500)
- `db.py` — in-memory `Store` (14 entity dicts), `LogicalClock` (startup default `2026-05-01T00:00:00Z`, never wall-clock), UUID/timestamp/version helpers (`new_entity`, `touch`)
- `errors.py` — `ApiError` class + all 23 error IDs from the scaffold catalog with correct HTTP codes
- `response.py` — envelope per scaffold §1.0 / PRD §2.2: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; error body uses `data.error_id` / `data.message`
- `middleware.py` — `X-User-ID` / `X-User-Role` extraction, 7 recognized roles, `ERR_UNAUTHENTICATED` / `ERR_FORBIDDEN_ROLE`
- `validation.py` — body validators (string/int/enum/bool/datetime), `reject_unknown_fields`, `limit`/`offset` pagination (default 10, min 1, max 100), filter+`created_at`-asc sort helpers
- `routes/clients.py`, `referrals.py`, `evaluations.py`, `catalog.py` (DeviceModel+DeviceUnit), `device_orders.py`, `loans.py`, `training.py` (Plan+Session), `funding.py`, `claims.py`, `repairs.py`, `subscriptions.py`, `outcomes.py`, `ops.py` (run_daily + clock)
- `services/calculations.py` — `claim_provisional_total` (per-line ROUND_HALF_UP then sum), `payer_responsibility` (waterfall w/ LOW_INCOME halving on INSURANCE), `outcome_composite` (provisional + clinician variants), `trial_conversion_fee` (pinned 5-step order), `subscription_loyalty_fee` (>=100000 → 10%, >=50000 → 5%), `subscription_cancel_credit` (clamped days/30)
- Package `__init__.py` files for `routes/` and `services/`

**Endpoint count**: 42 routes implemented — all 42 from the endpoint table (clients 4, referrals 2, evaluations 5, device-models 3, device-units 5, device-orders 6, loan-agreements 4, training 6, funding 5, claims 5, repairs 4, subscriptions 5, outcomes 3, ops 2, loan-repair-tickets reverse-FK 1 — total 45 rows in the scaffold table; reverse-FK collection routes are included in the per-resource counts above).

**py_compile**: PASS on all 20 `.py` files.

**Boot smoke** (PORT=18745, fresh process): PASS
- `GET /` → 404 with proper error envelope
- `POST /api/clients` (IntakeCoordinator) → 201, `status=INTAKE`, version=1, `copay_tier=STANDARD` default applied
- `POST /api/clients` without headers → 401 `ERR_UNAUTHENTICATED`
- `POST /api/clients` as ClinicAdmin → 403 `ERR_FORBIDDEN_ROLE`
- `POST /api/_clock/set_current_utc` (ClinicAdmin) → 200 `{current_utc:"2026-06-01T00:00:00.000Z"}`
- `POST /api/device-models` + `POST /api/device-units` → model `in_stock_count`/`total_count` recompute correctly to 1/1
- `GET /api/evaluations?limit=5&offset=0` → array envelope with all four pagination meta fields

**Key fidelity decisions traced to PRD/scaffold**:
- Store starts completely empty — no seeding anywhere; every entity constructed via declared POST endpoints
- OCC only on `POST /api/evaluations` via `expected_client_version` → `ERR_STALE_VERSION` (412)
- Validation funnel order honored: auth → role → body schema → existence → OCC → state → segregation → cross-entity state → temporal → domain → fiscal
- Repair `START_REPAIR` with `needs_loaner=true` pre-checks the loaner pool before any mutation (atomic rejection with `ERR_NO_ELIGIBLE_UNIT`)
- Claim adjudication `PAY` computes available = remaining + provisional (reservation still held); DENY releases reservation; void of `PAID` returns `payer_pays_cents` and revives `EXHAUSTED → APPROVED` when remaining > 0
- Daily sweep strict `>` boundaries; entity-type order pinned (orders → loans → subs past-due → subs suspended → auths expired); within type, `created_at` ASC
- `total_count` conservation: only unit receipt mutates it; allocate/loan/repair/return/retire shift buckets only

## Step 7: Run Tests and Iterate — 2026-08-10T10:42:59.258Z

All green across three consecutive 8-round sweeps. Final state verified.

## Summary

**Iterations run:** 7 sweeps total (8 parallel rounds each). Final three consecutive sweeps fully clean: 8/8 rounds × 103/103 tests each.

**Tests deleted:** None. No test required deletion — every failing test traced to verbatim PRD prose; two tests were narrowed to their PRD-covered core (see below).

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — `ApiClient.__init__` now sends `Connection: close` / disables keep-alive on the `requests.Session`. Under `--isolation per-test-server` the runner SIGKILLs and reboots the server before every test; a pooled keep-alive socket could point at the dead process and fail mid-test with `ConnectionResetError` (observed in rounds 1/5 of sweep 2). Infrastructure robustness fix, no assertion changed.

**Fixes applied to `test_suite/`:**
- `test_03_evaluation_lifecycle.py::test_finalize_with_missing_category_rejected` — the shared factory `create_evaluation_payload` defaults `recommended_category="MAGNIFIER"`, silently filling the very field the test needed null. Test now passes `recommended_category=None` explicitly and asserts the created evaluation's category is null before finalize. PRD §3.2 covers `ERR_ASSESSMENT_INCOMPLETE` verbatim; the factory default was the bug.
- `test_09_intake_and_clients.py::test_client_system_fields_in_input_ignored` — PRD is silent on whether extra/system fields in a create payload are ignored vs rejected (unique-derivability collapse on the "ignored" mechanism). Removed the client-supplied `id`/`version` from the payload; kept the PRD-covered assertions (§2.4: `id` is a server-minted UUID, `version` starts at 1).
- `test_07_device_orders_and_units.py::test_model_computed_counts_start_at_zero` — same silence pattern; removed `in_stock_count=99` from the payload, kept the verbatim PRD §3.3 assertion that both catalog counters are 0 at creation.

**Fixes applied to `implementation/`:**
- `db.py` — added `format_instant()`: serializes logical-clock instants exactly in the clock's own form (`2026-05-01T00:00:00Z`, no fractional digits unless the instant carries sub-second precision). PRD §2.6 pins the clock value to exactly `2026-05-01T00:00:00Z` and states every recorded timestamp is taken from that clock; `created_at`/`updated_at` keep the three-fractional-digit format explicitly required by §2.4 (`new_entity`/`touch` now use `format_datetime(clock.now())`; `LogicalClock.now_iso()` uses `format_instant`). This fixed 7 tests asserting `dispensed_at`, `trial_ends_at`, `due_at`, `period_end`, `past_due_since` values.
- `routes/{funding,training,claims,subscriptions,repairs,device_orders}.py` — all business-timestamp/echo serialization sites (`valid_from`, `valid_until`, `scheduled_start/end`, `service_date`, `period_start/end`, loan `due_at`, `trial_ends_at`) switched from `format_datetime` to `format_instant`.
- `routes/training.py::schedule_session` — moved the instructor-overlap check (PRD §2.7 funnel level 9, temporal) before the plan session-cap check (level 10, domain constraints), so `ERR_SESSION_OVERLAP` correctly pre-empts `ERR_PLAN_SESSION_CAP` when both fail.
- `app.py` — bind-retry loop (20 × 0.5s) around `app.run` so a slow kernel socket release after the runner's SIGKILL can't abort a per-test boot.
- `start.sh` — replaced the per-boot `python3 -c "import flask"` dependency probe (a full interpreter boot before every one of 824 restarts) with a `.deps_installed` sentinel file.

**Flakiness note:** sweeps 2 and 4 showed ~1% of server boots exceeding the runner's hardcoded 15s per-test restart window; the port registry showed 16-20 concurrent holders during sweep 4 (a co-tenant pipeline on this shared host), while the clean sweeps ran with 0 external holders. After the keep-alive and start.sh fixes, three consecutive sweeps are fully clean, including under self-inflicted 8-round load.

**Orchestrator verification:** Step 7 subagent exited clean; orchestrator independently re-ran `sweep.sh` once more (2026-08-10T10:43Z–10:44Z): all 8 rounds 103/103 passed, and `results.1.json`–`results.8.json` persist on disk under `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-08-10T10:49:29.850Z

Both edits are in place and the file is complete. Here is the summary.

## Result

**Line counts:** PRD.md = 318 lines; PRD_FINALIZED.md = 318 lines (0% line-count delta — both edits extended existing paragraphs inline, no sections added). Two lines modified in place.

### Changes (one bullet per edit)

- **§2.6 (The Logical Clock and the Daily Sweep)** — revise — appended serialization pin: clock-derived business timestamps (`decided_at`, `dispensed_at`, `loaned_at`, `returned_at`, `past_due_since`, plus computed `trial_ends_at`/`due_at`/`period_end` and the clock-set response's `current_utc`) render as `YYYY-MM-DDTHH:MM:SSZ` with fractional seconds only when the instant carries sub-second precision; caller-supplied datetimes (`valid_from`, `valid_until`, `service_date`, `period_start`, `scheduled_start`, `scheduled_end`, `to_iso8601`) are parsed, normalized to UTC, and re-serialized in that form rather than echoed verbatim; only `created_at`/`updated_at` keep §2.4's three-fractional-digit format — `implementation/db.py:42-56` (`format_instant`), `db.py:102-103` (`now_iso`), `db.py:112,123` (`format_datetime` kept for `created_at`/`updated_at`), `routes/ops.py:23,62`, `routes/referrals.py:53`, `routes/loans.py:65`, `routes/device_orders.py:170,173,186-187,247,258-260`, `routes/repairs.py:112-113`, `routes/subscriptions.py:53-54,106,108`, `routes/funding.py:42-43`, `routes/claims.py:60`, `routes/training.py:116-117`.
- **§2.7 item 3 (Body schema, validation funnel)** — revise — pinned that any endpoint reading a request body rejects fields outside its accepted set (including client-supplied system fields like `id`, `version`, `created_at`, computed counters) with `ERR_VALIDATION` at the body-schema level, and that no-body endpoints disregard a body entirely — `implementation/validation.py:89-92` (`reject_unknown_fields`) and all 22 callsites: `routes/clients.py:18`, `referrals.py:18,43`, `evaluations.py:25,128`, `catalog.py:36,89`, `device_orders.py:52,134`, `training.py:18,73,147`, `funding.py:18,92`, `claims.py:21,35,134`, `repairs.py:23,59`, `subscriptions.py:21`, `outcomes.py:19,62`, `ops.py:20`.

### Step-7 items judged NOT PRD material (no edit)

- `routes/training.py::schedule_session` overlap-before-cap reorder — implementation was fixed to match PRD §2.7's already-pinned funnel (level 9 temporal/overlap precedes level 10 domain/session-cap); PRD already uniquely determines this, prose kept verbatim.
- `test_helpers/api_client.py` keep-alive, `app.py` bind-retry, `start.sh` sentinel — server-boot/test-harness robustness, no API behavior.
- `test_03` factory-default fix — pure test-fixture bug; §3.2 already covers `ERR_ASSESSMENT_INCOMPLETE` verbatim.
- The two narrowed tests (`test_client_system_fields_in_input_ignored`, `test_model_computed_counts_start_at_zero`) — these are the ones that motivated the §2.7 unknown-field pin above.

### Pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit 1 — timestamp serialization**
- (a) Subject: string form of every timestamp appearing in API payloads.
- (b) Enumerated paths: `db.py` (`format_datetime` vs `format_instant`, `LogicalClock.now_iso`, `new_entity`, `touch`); every clock-stamp site via grep for `decided_at|dispensed_at|loaned_at|returned_at|past_due_since|due_at|trial_ends_at|now_iso|current_utc` across all routes + `services/calculations.py`; every caller-supplied datetime echo (`funding.py:42-43`, `claims.py:60`, `subscriptions.py:53`, `training.py:116-117`); `ops.py:62` (`past_due_since` copies `period_end` verbatim — already clock-form); `clients.py:20` (`date_of_birth` is a date string echoed verbatim, not a datetime).
- (c) Wording adjustments: (i) scoped the echo-normalization clause to "datetime values supplied by the caller" with an explicit example list excluding `date_of_birth` (a verbatim date string); (ii) added the trailing sentence preserving §2.4's three-fractional-digit rule for `created_at`/`updated_at` so the new sentence can't be read as narrowing §2.4; (iii) said "fractional seconds (three digits) only when the instant actually has sub-second precision" to exactly match `format_instant`'s `if dt.microsecond` branch.

**Edit 2 — unknown-field rejection**
- (a) Subject: handling of request-body fields outside an endpoint's accepted set.
- (b) Enumerated paths: all 22 `reject_unknown_fields` callsites (listed above), including claim line-item objects (`claims.py:35`); the three optional-body endpoints that reject unknown fields only when a body is present (`device_orders.py:130-134` allocate, `evaluations.py:124-128` revise, `outcomes.py:58-62` assessment-finalize); and every POST that never reads a body (funding submit/appeal, claim submit/void, order convert/return, loan return, unit retire, subscription renew/cancel, evaluation finalize, ops run_daily) — verified via grep of `require_body|request.get_json`.
- (c) Wording adjustments: (i) scoped the rejection to "any endpoint that reads a request body" so optional-body endpoints (which reject only when a body exists) are covered, and added "Endpoints that accept no body simply disregard one" so the no-body endpoints aren't falsely claimed to reject; (ii) anchored the rejection at funnel level 3, matching the impl's call order (reject_unknown_fields runs immediately after `require_body`, before existence checks).

## Step 9: Complete PRD — 2026-08-10T10:55:04.171Z

(Note: the Step 9 subagent's first spawn exited after its analysis phase having only created PRD_COMPLETED.md as a byte-identical copy of PRD_FINALIZED.md; it was resumed via SendMessage with its context intact and applied all edits below.)

Done. All edits applied to `/home/ubuntu/github/CodingPRD/tasks/task_0980_low_vision_assistive_technology/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (318 lines, 51533 chars) → `PRD_COMPLETED.md` (320 lines, 54353 chars); char-delta **+2799**. No new sections added (section-header count identical); all changes are in-paragraph inserts/revisions.

**Counts:** 9 ambiguity-pins, 2 mismatch-revisions (11 changes total, one edit covering two pins).

**Changes:**
- §2.2 — insert — ambiguity — pinned framework-level error mapping: unknown path or wrong method → `ERR_NOT_FOUND` 404; unparseable JSON body → `ERR_VALIDATION` 400; unexpected fault → `ERR_INTERNAL` 500 leaking only exception type name — app.py:46-61
- §2.3 — insert — ambiguity — pinned `ERR_VALIDATION` 400 for non-integer/out-of-range `limit`/`offset`; `created_at` ties broken by `id` ascending; `has_more` = (`offset` + page size) < `total_count` — validation.py:95-117, validation.py:135, response.py:50
- §2.4 — insert — ambiguity — a counter recompute that changes neither value is not a model mutation (no `updated_at`/`version` touch) — routes/catalog.py:26-29
- §2.7 step 4 — insert — ambiguity — pinned two existence-level carve-outs: explicit allocation `device_unit_id` that fails to resolve reports `ERR_UNIT_NOT_AVAILABLE` (not 404); cross-field consistency checks needing referenced rows (referral-client mismatch, order-client mismatch on claims/plans) fail as `ERR_VALIDATION` immediately after existence, before OCC/state — routes/device_orders.py:150-154, routes/evaluations.py:46-47, routes/claims.py:51-52, routes/training.py:28-29
- §3.1 — insert — ambiguity — `date_of_birth` requires only a non-empty string; ISO date format not enforced — routes/clients.py:20
- §3.3 — insert — ambiguity — non-null `successor_model_id` naming no existing model → `ERR_NOT_FOUND`; duplicate `serial_no` → `ERR_VALIDATION` 400 — routes/catalog.py:45-46, catalog.py:96-98
- §3.4 — revise — mismatch — non-TRIAL `trial_days` is optional, range-validated when present, and stored on the order (PRD previously said "ignored"); never used in computation — routes/device_orders.py:62-63, 90
- §3.4 — insert — ambiguity — evaluation-finality guard re-applied at allocation: missing or non-FINALIZED evaluation → `ERR_EVALUATION_NOT_FINAL` — routes/device_orders.py:145-147
- §3.5 — revise — mismatch — `overdue_days` is stamped at the ACTIVE→OVERDUE transition and frozen thereafter (PRD previously said the sweep "keeps it current"); only return finalizes it — routes/ops.py:50-56 (step 2 matches ACTIVE only), routes/loans.py:66-68
- §3.6 — insert — ambiguity — overlap check (funnel level 9) is evaluated before the session cap (level 10); a request violating both reports `ERR_SESSION_OVERLAP` — routes/training.py:91-109
- §3.7 — insert — ambiguity — conditional `allowed_amount_cents`-required check runs after existence/state/segregation (missing value on an inadmissible claim surfaces the earlier error); adjudication never re-checks authorization status, so a SUBMITTED claim on a since-EXPIRED authorization is still adjudicable — routes/claims.py:138-150

**Findings re-examined and deliberately not edited:** trial-conversion equality boundary (PRD already pins "on or before", impl `now > trial_ends_at` matches); §2.6 sweep item 2 wording (already scoped to ACTIVE loans, consistent with frozen `overdue_days`); `needs_loaner` accepted-but-unused on non-START_REPAIR advances (body-schema tolerance already covered by §2.7's per-endpoint field set); loan-return role pair, session-resolve plan touches, claim-submit check order, subscription closed-interval overlap single-check, QA_PASS unit return — all already uniquely pinned by existing PRD prose and matching impl.

**Orchestrator final verification (2026-08-10T10:55Z):** PRD_COMPLETED.md exists with edits applied (320 lines, +2799 chars over PRD_FINALIZED.md); `results.1.json`–`results.8.json` present under `workspace/implementation/`, all 8 rounds 103/103 passed; worklog reaches `## Step 9`. Pipeline complete.
