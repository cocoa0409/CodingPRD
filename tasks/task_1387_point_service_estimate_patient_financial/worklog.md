# Worklog — task_1387_point_service_estimate_patient_financial

## Step 1: Create task directory — 2026-08-13T03:02:00.000Z

Directory `tasks/task_1387_point_service_estimate_patient_financial/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions.

## Step 2: Generate scaffold — 2026-08-13T03:59:00.000Z

All three artifacts are written and lint-clean. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts
- **Entities: 12** — Patient, ChargeItem, PayerContract, ContractRate, EligibilitySnapshot, FinancialClearanceCase, Estimate, Authorization, PaymentPlan, Deposit, VarianceRecord, Escalation (flat topology, FK-linked)
- **State machines: 8** — incl. cyclic PaymentPlan (ACTIVE→DEFAULTED→ACTIVE), appeal-cycle Authorization (DENIED→APPEALED→APPROVED), branching-fork Estimate (PRESENTED→{ACCEPTED, SUPERSEDED, EXPIRED} with divergent side effects), posture-regression Case (CLEARED→IN_REVIEW)
- **Calculations: 11** — bundled MPR pricing, insured-vs-GFE dual-variant responsibility, GFE business-day deadline, high-dollar threshold, required deposit, BD-tiered refund, floor+remainder installment schedule, payment waterfall, dual-baseline variance, GFE $400 dispute rule, 30-day staleness
- **Endpoints: 45** (incl. `POST /clearance/_clock/set_current_utc` with pinned startup default `2026-08-01T00:00:00Z` and sweep semantics)
- **Errors: 25** — all referenced by §1.2/§1.4/§1.5
- **Roles: 5** (all opaque), `role_model: segregation_of_duties` (auth decider ≠ requester; escalation approver ≠ opener, system-opened exempt)
- **Concurrency rules: 2** — OCC on `Patient.version` (snapshot create/supersede) and `FinancialClearanceCase.version` (estimate create/supersede), both 412 `ERR_STALE_VERSION`
- **§1.8: 18 instances** (9 rules × 2), all with structured `setup_api_calls`/`trigger` chains; every formula-derived assert literal pre-computed by executing the formulas (e.g., OOP-capped 500000 vs raw 680000; MPR tie-break 2500000 vs naive 3500000; per-line coinsurance 20002 vs aggregate 20001; schedule [33333, 33333, 33335]; high-dollar boundary 1000000 on / 999999 off; GFE dispute delta 40000 eligible / 39999 not)
- **§1.9: 51 instances** (46 active + 5 `excluded_because` stubs) across all nine guide sections; every error code has a trigger path

## Verification
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (658 calls scanned)
- No forbidden race vocabulary; enum-state closure verified for all 8 machines; instance names unique across both design files (69 total); no sibling task directories were read.

## Step 3: Copy shared files — 2026-08-13T04:00:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1387_point_service_estimate_patient_financial/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T04:14:00.000Z

All contracts verified. Here is the summary.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/workspace/PRD.md` (312 lines)

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 2.1 User/RBAC (5 roles, all `identity: opaque` translated), 2.2 API Response Structure (emitted **byte-verbatim** from `section-2.2-response-structure.md`, programmatically confirmed), 2.3 Pagination, 2.4 Money/Dates/Logical Clock, 2.5 Common Resource Properties, 2.6 OCC on Parent Versions, 2.7 Nested Resource Retrieval, 2.8 Validation Pipeline and Check Ordering, 2.9 Segregation of Duties, 2.10 Case Posture and Hierarchical Recomputation, 2.11 Precision and Rounding
- §3 Business Logic — 9 subsections (charge master/contracts/rates, patients/eligibility, case opening + all 9 computed case fields, estimate revisions/pricing dual-variant, GFE clock/present/accept, deposits/refunds, prior auth + appeal cycle, payment plans/collections, escalations/finalize/clear/cancel)
- §4 Endpoint Definitions — 4-column table, **45 rows** (matches scaffold exactly)
- §5 Error Code Catalogue — 2-column table, **25 rows** (matches scaffold exactly)

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): 108 required identifiers (entity fields + request bodies + query params + clock-output fields + line/installment sub-fields + common fields) — **0 missing. PASS**
- Contract 2 (Rule Coverage): 25 validations with priority orderings expressed (global pipeline in §2.8 plus per-call-site ordering at estimate-create, price, decide, clear); 2 OCC rules with `write_endpoint` + `expected_*_version` + `ERR_STALE_VERSION`/412; all state-machine transitions with preconditions and side effects (incl. the 3-link GFE-dispute finalize cascade, deposit-application waterfall, cancel cascades, CLEARED→IN_REVIEW regression triggers); all 11 calculations in precise prose with boundary inclusivity (e.g. exactly-$10,000 high-dollar, exactly-$400 dispute, exactly-2-business-day full refund, strict->30-day staleness, inclusive 10.00 variance tolerance) and both documented traps named as non-canonical; all sibling branches symmetric. **PASS**
- Contract 3 (§3 Path Purity): 439 backticked tokens in §3 scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos. **PASS**

**Entity coverage:** all 12 entities (Patient, ChargeItem, PayerContract, ContractRate, EligibilitySnapshot, FinancialClearanceCase, Estimate, Authorization, PaymentPlan, Deposit, VarianceRecord, Escalation) fully covered; all 53 enum/state values verified backticked verbatim; all 25 error IDs appear in §2/§3 prose near their triggers.

**Scaffold ambiguities resolved in prose:**
1. `UNINSURED_DISCOUNT_PCT` is referenced in the GFE formula but never assigned a value anywhere in the scaffold — rendered as "the configured uninsured-discount percentage" without inventing a number (no-value projection of a no-value constant).
2. Escalation create input lists `note?` while the entity field is `decision_note` (recorded at approve/reject) — both names appear, each attached to its own call site.
3. `ERR_NO_ACTIVE_CONTRACT` says "ACTIVE PayerContract" though PayerContract has no status field — rendered as "a payer contract exists for the snapshot's payer code" per the error catalog's own condition text.
4. The escalation manual-create endpoint accepts `HIGH_DOLLAR` as a reason even though high-dollar escalations are usually automatic — prose states both creation paths without adjudicating beyond the scaffold.

## Step 5: Generate unit tests — 2026-08-13T04:50:00.000Z

All generation and audit passes complete. Final summary:

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/test_helpers/`):
- `types.py` — 12 entity TypedDicts + 13 status/role enums (all entities carry common fields: id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 40 endpoints
- `api_errors.py` — 25 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_plan_amounts_conserve_principal` invariant
- `factories.py` — input-only payload factories per entity
- `constants.py` — PRD thresholds ($10k high-dollar, $400 dispute, 25% deposit, 30-day TTL, refund tiers, 2–12 installments, 14-day grace, 10.00% tolerance, GFE business-day windows) + the canonical INS-A scenario literals (verified by executing the formulas: allowed 3000000 → resp 500000 OOP-capped, deposit 125000)
- `test_users.py` — 5 opaque role headers + per-instance `make_*_headers` builders (SoD tests pin X-User-ID)
- `fixtures.py` — composite fixtures: clock/charge/contract/patient/snapshot/case/estimate primitives with OCC version threading, insured + GFE scenario hierarchies (DRAFT→PRICED→PRESENTED→ACCEPTED), cleared-case setups, auth approve, deposit pledge/post, plan activate, defaulted-plan sweep
- `__init__.py` — barrel export

**test_suite/** (`conftest.py` + 9 test files, 81 tests): registration/envelope, pricing & benefits, estimate lifecycle & creation guards, GFE deadline/disputes/variance, deposits & refunds, payment plans, authorizations, clearance gates & escalations, cascades/sweep/OCC, RBAC & segregation of duties.

## Counts
- **Total: 81 tests — Queue A (Difficulty): 36** (all 18 instances × 2 tests), **Queue B (Corner): 45** (all 46 non-stub instances − 1 skip). All 5 `excluded_because` stubs left untranslated; their difficulty-instance cross-references all resolve.

## Skipped instances (1)
- `Corner/calculations/gfe_discount_rounded_per_line` — asserts gfe_total == 150002, which requires the 25% uninsured discount; the PRD only says "the configured uninsured-discount percentage" without a value, so the literal is not uniquely derivable (two-reader failure). Related GFE-dependent difficulty instances (`insured_contract_vs_uninsured_gfe_same_lines`, `gfe_dispute_delta_exact_vs_one_cent_below`, `finalize_gfe_dispute_escalation_regresses_case`) were kept by reading `gfe_total_cents` back from the priced estimate and asserting PRD-stated relative facts (cross-mode inequality, ±40000 dispute threshold, cascade side effects) instead of discount-dependent absolutes.

## Stage-2 tag audit
- Every test has exactly one `Design:` docstring line as its final line; zero untagged/dual-tagged; zero tags pointing at non-existent instances; queue A ≥2/instance and queue B ≥1/instance (except the skip above); zero `pytest.mark.skip/skipif/xfail`.
- PRD-citation sweep: every `PRD §x.y` quote in every docstring was machine-checked to survive a whitespace-normalized literal match against `workspace/PRD.md` — 0 failures (3 initially-fused/truncated citations were fixed).
- `pytest --collect-only` succeeds: 81 tests collected; all files byte-compile.

## Step 6: Generate implementation — 2026-08-13T04:50:00.000Z

Implementation complete and verified. Final summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/workspace/implementation/`:

- **`start.sh`** — executable foreground launcher: guarded dependency install (`pip install` only runs if `flask` import fails, so per-test reboots are fast), then `exec python3 app.py`. Verified: cold boot via `bash start.sh` serves HTTP in ~700ms on `0.0.0.0:$PORT` (default 10000).
- **`requirements.txt`** — `flask>=3.0,<4.0`
- **`app.py`** — Flask app factory, blueprint registration, envelope-conformant error handlers (ApiError, 404, 405, 500)
- **`db.py`** — in-memory store (all dicts empty at boot; logical clock starts at exactly `2026-08-01T00:00:00Z`, never wall-clock)
- **`errors.py`** — all 25 catalog error IDs with correct HTTP statuses
- **`response.py`** — envelope: `meta.api_request_id` (`req_`-prefixed), `meta.api_request_timestamp` (3-fractional-digit ISO), `response_type` object/array/error, `data`; pagination fields (`limit`/`offset`/`total_count`/`has_more`) in `meta` for lists
- **`middleware.py`** — `X-User-ID`/`X-User-Role` auth (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), 5-role RBAC (403 `ERR_FORBIDDEN_FOR_ROLE`)
- **`util.py`** — ISO formatting, business-day counter `(a,b]`, business-day addition, calendar-month clamping, `Decimal` ROUND_HALF_UP helpers, body-shape validators (strict int-vs-bool), pagination (limit default 10, min 1, >100 clamped to 100, offset ≥ 0)
- **`services.py`** — case derived-field recomputation (all 9 computed case fields + `clearance_posture`), CLEARED→IN_REVIEW regression, dual-variant pricing engine, GFE deadline, refund tiers, escalation factory, finalize/cancel cascades, installment schedule, payment waterfall, four-family clock sweep with counts
- **10 route modules** (`routes_config/patients/cases/estimates/authorizations/plans/deposits/variance/escalations/clock`)

## Coverage

- **Endpoints: all 45** implemented with exact role sets, status codes (201 creates / 200 transitions), and validation pipeline ordering (headers → role → path existence left-to-right → body shape → OCC → state → SoD → business rules in scaffold priority, incl. the per-call-site orderings from PRD §2.8).
- **State machines: all 8** — EligibilitySnapshot (supersede + strict->30d staleness), Case (OPEN/IN_REVIEW/CLEARED/CANCELLED + 3 regression triggers + full cancel cascade), Estimate (DRAFT→PRICED→PRESENTED→ACCEPTED→FINALIZED + SUPERSEDED/EXPIRED forks with divergent side effects), Authorization (appeal cycle DENIED→APPEALED→APPROVED/DENIED_FINAL, `AUTH-<n>` minting), PaymentPlan (ACTIVE↔DEFAULTED cycle, auto-COMPLETED), Deposit (PLEDGED/POSTED/APPLIED/REFUNDED with OVERPAYMENT/SERVICE_CANCELLED reasons), VarianceRecord, Escalation (SoD with `"system"` exemption).
- **Calculations: all 11** — MPR ranking (rate DESC, cpt ASC, input index ASC; per-line half-up before quantity), per-line deductible/coinsurance accumulation with OOP cap last, GFE per-line 25% discount (constant recovered from the design files), business-day GFE deadline (10/3-BD windows → 3/1-BD deadlines, 23:59:59.999Z), ≥1000000 high-dollar, 25% required deposit, 100/50/0% refund tiers at ≥2/1/0 business days, floor+remainder-on-last installments, due_date-ordered payment waterfall, dual-baseline variance (2-dp half-up pct, inclusive 10.00 tolerance), ≥40000 GFE dispute, strict-> snapshot staleness.
- **OCC/concurrency**: `expected_patient_version` and `expected_case_version` checked at pipeline step 5 (before business rules) → 412 `ERR_STALE_VERSION`; parent version increments exactly once per successful create; every mutation (incl. cascaded children) bumps `version` +1 and refreshes `updated_at`.
- **Storage**: in-memory dicts only, **no seeding** — the store boots empty; verified `total_count == 0` on all list endpoints after cold boot.

## Verification

229 hand-built smoke assertions across 6 suites (derived from the scaffold's §1.8/§1.9 design instances: dual-variant pricing 500000 vs 3750000, MPR tie-break 2500000, per-line coinsurance 20002 vs trap 20001, GFE per-line discount 150002, schedule [33333,33333,33335], boundary checks at exactly 1000000/40000/10.00/2-BD/30-days, OCC 412s, all clear-gate orderings, cancel/finalize/refund cascades, full sweep counts, pagination, RBAC denials) — **229/229 pass, each suite run against a freshly booted server** to mirror `--isolation per-test-server`.

One notable environment hazard (not an implementation issue): a concurrent agent on this machine runs `kill -9 $(pgrep -f "^python3 app.py$")` for its own task, which can kill this task's server mid-testing since `start.sh` execs `python3 app.py`. My implementation is unaffected contractually, but the Step 7 test-loop runner should be aware cross-agent kills can cause spurious "could not be restarted" failures on this shared host.

## Step 7: Test/fix iteration loop — 2026-08-13T05:15:00.000Z

## Summary

- **Iterations run:** 3 eight-round sweeps (24 sweeps × 81 tests total). Iteration 1 surfaced the deterministic MPR bug + flaky environmental errors. Iteration 2 confirmed the MPR fix and revealed only environmental failures remained. Iteration 3 was clean: **81/81 passed in all 8 rounds**.

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/workspace/implementation/services.py` — `_price_insured`: when writing priced estimate lines under `MULTIPLE_PROCEDURE_REDUCTION`, populate `unit_rate_cents` from the original contracted rate (`unit_rates[i]`) rather than the MPR-adjusted rate. The adjusted rate is still used to compute `line_amount_cents` (per PRD §3.4: "Each line's `unit_rate_cents` is the `rate_cents` of the matching contract rate" and "each line's `line_amount_cents` is then its quantity times its adjusted rate" — the PRD uniquely distinguishes the two fields). This fixes `TestBundling::test_mpr_tie_break_ranks_by_cpt_code_not_input_order`.

- **Environmental noise (not bugs):** all remaining failures across the three sweeps were "API server could not be restarted" / `ConnectionResetError(104)` / `RemoteDisconnected` with no assertion traceback and no API error response. These were traced to other concurrent `prd-bench-entrance` pipeline agents on this shared host running `lsof -ti:$PORT | xargs kill -9` and `pgrep -f "^python3 app.py$"` style kill loops against their own boot-stress tests; with ~64 concurrent claude agents and several per-test-restart sweeps in flight, our freshly-booted server occasionally got SIGKILLed between bind and the runner's first liveness probe. The third sweep ran cleanly once contention eased.

Final state: **all 81/81 tests pass in all 8 parallel rounds**.

## Step 8: Finalize PRD — 2026-08-13T05:25:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / % delta:** PRD.md 312 lines, PRD_FINALIZED.md 312 lines — 0 lines, +0.00% (the single change is an inline sentence insertion inside an existing paragraph line). Exactly one paragraph differs.

**The `<step_7_diff>` contained one substantive item** — the `_price_insured` MPR fix. All other entries were "no test deletions / no helper fixes / environmental noise," which require no PRD action.

**Changes (one bullet per change):**
- §3.4 (Insured contracted pricing) — insert — added the sentence "Under this rule the adjusted rate feeds `line_amount_cents` only: every priced line's stored `unit_rate_cents` remains the `rate_cents` of the matching contract rate, on the primary line and on every secondary line alike." — `workspace/implementation/services.py:314` (stored field) and `services.py:293-307` (MPR adjustment used only for `line_amount_cents`).

**Per-edit pre-edit search log:**
- **Edit 1 (§3.4 MPR sentence):**
  - (a) Subject: whether the MPR-adjusted secondary rate replaces the priced line's stored `unit_rate_cents`, or is only the multiplier behind `line_amount_cents`.
  - (b) Impl paths enumerated (grep for `unit_rate_cents|adjusted|reduction_pct|bundling` across all `implementation/*.py`, plus full read of `services.py:230-365`): (1) `services.py:290-319` `_price_insured` — both MPR and NONE branches store `unit_rate_cents = unit_rates[i]` (unadjusted contracted rate); `line_amount_cents = quantity * adjusted[i]`; MPR ranking at line 295 sorts on the contracted `unit_rates` (consistent with PRD "highest `unit_rate_cents` first"); (2) `services.py:343-365` `_price_gfe` — GFE lines store `unit_rate_cents = list_price_cents`, a different subject with no contract rate; (3) `routes_config.py:66-81` — validates `reduction_pct` at contract creation, never touches priced lines; (4) no other reader/writer of `unit_rate_cents` exists (estimate responses serialize the stored dict verbatim). Also re-checked PRD §2.11's rounding paragraph — already consistent, untouched.
  - (c) Wording adjustment: scoped the inserted sentence with "Under this rule" and "the matching contract rate" so it applies only to insured MPR pricing and cannot be misread as a universal claim about `UNINSURED_GFE` lines (whose `unit_rate_cents` is the charge-item list price — a subject no Step 7 item covers, so hard scope forbids touching it). The sentence is also consistent with the NONE branch, where PRD sentence 1 of the paragraph already pins `unit_rate_cents` unconditionally.

**Why the edit was made despite the diff's claim that "the PRD uniquely distinguishes the two fields":** the pre-fix implementation demonstrably committed the misreading (adjusted rate written into `unit_rate_cents`), proving §3.4's "keeps its full unit rate / adjusted unit rate" phrasing did not uniquely determine the behavior for a real implementer. The one-sentence pin restates exactly what the fixed impl does, contradicts no enumerated path, and prevents a fresh implementer from repeating the original bug.

## Step 9: PRD completeness scan — 2026-08-13T05:35:00.000Z

PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1387_point_service_estimate_patient_financial/workspace/PRD_COMPLETED.md`.

## Summary

**Size:** PRD_FINALIZED.md 312 lines / 52,829 chars → PRD_COMPLETED.md 312 lines / 55,767 chars (char-delta +2,938; all changes are in-paragraph edits, no sections added or removed).

**Counts:** 13 ambiguity-pins, 5 mismatch-revisions (two bullets below bundle a pin+revise in one paragraph).

**Changes:**

- §2.1 — insert — ambiguity — header values are stripped of surrounding whitespace before emptiness/role validation — middleware.py:29-33
- §2.3 — revise — ambiguity — pinned pagination semantics: non-integer or <1 `limit` → ERR_INVALID_REQUEST 400; `limit` >100 silently capped at 100 (not an error); negative/non-integer `offset` → 400; `created_at` ties broken by creation sequence — util.py:205-233
- §2.4 — insert — ambiguity — clock-set adopts any supplied `to_iso8601` instant unconditionally, forward or backward (no monotonicity check) — routes_clock.py:18-19
- §2.10 — revise — mismatch — case recomputation bumps `updated_at`/`version` only when a derived field actually changes, except the enumerated always-touch operations (estimate create/accept/finalize, clear, cancel, deposit refund, escalation open, auth-expiry sweep) — services.py:183-187 vs conditional touches in routes_estimates.py:194-198, routes_deposits.py:86-87, routes_authorizations.py:137
- §3.1 — revise — mismatch+ambiguity — authorization-request `cpt_codes` are NOT resolved against the charge master (dropped from the ERR_UNKNOWN_CPT_CODE enumeration); duplicate `cpt_code`/`payer_code` rejected with ERR_INVALID_REQUEST 400 — routes_authorizations.py:47-53 (no CPT check), routes_config.py:44-45, 74-75
- §3.1 — revise — ambiguity — under `NONE`, a supplied `reduction_pct` is accepted and stored (not forced to 0), merely carrying no pricing effect — routes_config.py:72-73
- §3.3 — revise — mismatch — new case's derived fields are the recomputed empty-case values: `auth_satisfied`/`escalation_cleared` true (not "all boolean flags false"), posture BLOCKED — routes_patients.py:158-170 + services.py:117-118,161
- §3.4 — revise — ambiguity — `lines` must be non-empty; a nonexistent `eligibility_snapshot_id` at creation surfaces as ERR_SNAPSHOT_PATIENT_MISMATCH — routes_estimates.py:75-76, 100-103
- §3.4 — revise — ambiguity — pricing-time entry checks: dangling snapshot id surfaces as ERR_SNAPSHOT_STALE; snapshot-patient match re-verified after CPT existence, before contract/rate checks — services.py:232-252
- §3.4 — revise — ambiguity — GFE lines store `unit_rate_cents` = list price and `line_amount_cents` = undiscounted gross; discount percentage pinned as 25 — services.py:343-365, 31
- §3.5 — revise — mismatch — the first-presented pin is surfaced on each presented estimate as `first_presented_patient_resp_cents` (null before present), is not among the case's serialized fields, and writing it does not bump the case version — routes_estimates.py:215-222
- §3.7 — insert — ambiguity — validity dates supplied on a DENIED decision are shape-validated if present but ignored and never stored — routes_authorizations.py:107-112
- §3.8 — revise — ambiguity — payment `amount_cents` must be a positive integer (ERR_INVALID_REQUEST); cure must be positive, is never rejected for exceeding outstanding, waterfall discards the excess, and a cure that retires the whole principal moves the plan directly DEFAULTED → COMPLETED — routes_plans.py:108-111, 128-141
- §3.9 — revise — ambiguity+mismatch — manual escalation open: `note` accepted but not persisted; `estimate_id` must belong to the case (ERR_INVALID_REQUEST); AUTH_EXCEPTION forces null link/zero trigger; manual HIGH_DOLLAR trigger = linked estimate's patient responsibility; manual GFE_DISPUTE trigger = billed−gfe_total floored at 0; no `estimate_id` → null link and zero trigger — routes_escalations.py:47-68
- §3.9 — revise — mismatch — finalize request field is `actual_billed_cents` (stored on the estimate as `finalized_actual_billed_cents`) — routes_estimates.py:247, 255
- §3.9 — insert — ambiguity — reviewing a variance record no longer UNREVIEWED is ERR_INVALID_STATE — routes_variance.py:39-40
