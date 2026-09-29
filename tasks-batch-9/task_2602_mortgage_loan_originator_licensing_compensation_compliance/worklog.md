# Worklog — task_2602_mortgage_loan_originator_licensing_compensation_compliance

## Step 1: Create task directory — 2026-09-03T18:05:30.595Z

Created `tasks/task_2602_mortgage_loan_originator_licensing_compensation_compliance/` and `tasks/task_2602_mortgage_loan_originator_licensing_compensation_compliance/workspace/` at the pre-assigned path (index fixed by scenario number 2602; no auto-allocation scan performed, per orchestration instructions — other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T19:51:01.415Z

All three scaffold artifacts are complete and lint-clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3700 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2026 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4916 |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. The other two files each carry exactly their single required top-level key.

## SCAFFOLD.yaml counts
14 entities · 68 endpoints · 9 state machines (shape `cyclic`) · 8 calculations · 38 validation rules (single priority ladder 1–38) · 39 error codes · 7 roles (`segregation_of_duties`) · 2 OCC concurrency rules · `difficulty_level: beyond_expert`.

## §1.8 / §1.9 instance counts
- §1.8: 9 difficulty rules × 2 = **18 instances**, all with recipes.
- §1.9: **88 instances across all nine guide sections** = 60 recipes + 28 `excluded_because` stubs (entities 13/0, state_machines 8/5, calculations 6/7, validations 8/3, endpoints 5/1, errors 12/8, rbac 5/0, cross_cutting 1/4, consistency_model 2/0). All 18 §1.8 instance names are cited by at least one stub; all 39 declared error codes are referenced by a §1.8 or §1.9 instance; instance names are unique across the union of both files.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  908

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(The lint counts only recipe-bearing §1.9 instances; the 28 stubs are correctly not counted.) Tail of the corner file ends at the final `assert:` line of the last `consistency_model` instance.

## Design adjudications
- **`ops_run_checkpoint` layer minted no claim.** It is declared in `complexity_layers` but the claim-extraction guide has no row for it; the sweep's checkpoint semantics (idempotent re-run at the same instant, empty arrays, no double application) are asserted instead by the `endpoints` / `bulk_action` instance, and this is documented in an in-file comment rather than silently dropped.
- **Claim-type names for rows the guide leaves unlabelled.** Table 6 (Errors) and Table 7 (RBAC) contain prose, not claim-type rows, so I used `error_triggerable` for the errors section and `exclusive_operations` / `forbidden_operations` / `shared_operations` / `segregation_of_duties` / `identity_ownership` for rbac, plus `foreign_key_integrity` from the `flat`-topology row. Each is derived from a guide bullet, and the mapping is recorded in a comment above the section.
- **Error coverage was split rather than duplicated.** 19 of the 39 error codes are already triggered by earlier §1.9 sections; the errors section therefore carries 12 fresh recipes plus 8 stubs, with a header comment enumerating which codes are covered where.
- **Reaching narrowly-guarded errors.** `ERR_SPONSORSHIP_REQUIRED` is reached by activate → sponsor → relinquish (so the priority-14 clauses do not pre-empt it); `ERR_STATE_NOT_AUTHORIZED` on ad publish via `employment_status: SUSPENDED`; `ERR_PROHIBITED_COMP_VARIABLE` isolated by making weights sum to exactly 100; `ERR_SEGREGATION_OF_DUTIES` placed in rbac (both the drafter-approves and requester-decides arms) rather than duplicated in validations.
- **OCC drift made real, not synthetic.** The plan-assignment OCC recipe drifts the originator version with two genuine `PATCH /originators/{id}` writes and replays the identical body, instead of asserting an invented `version - 1`; the sponsorship OCC rule is stubbed to the §1.8 instance that already tests it.
- **Segregation of duties is tested per-user, not per-role**: one user id (`dual-1`) legitimately wears CompensationDesigner and ComplianceOfficer, which is the only way to falsify a role-only implementation.
- **Reinstatement recipe re-bases off the clock** (2026-09-02 → exp 2027-09-02 / window 2027-07-04; 2027-09-03 → exp 2028-09-02 / window 2028-07-04), and deliberately never runs a renewal completion so `ce_reporting_year` stays 2026 and the same 8 CE hours satisfy all three attempts — isolating the counter as the only variable.
- **One correctness fix during final review:** an audit-trail assertion referenced a non-existent `ORIGINATOR_CREATED` event type (the lint cannot catch bad enum *values*). The rbac shared-reads recipe now activates a licence so the audit read asserts the real `LICENSE_STATUS_CHANGED` / `LicensingAnalyst` / `sequence_no 1`; I re-verified every audit event literal in both design files against the declared enum.

## Step 3: Copy shared files — 2026-09-03T19:51:01.415Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T20:14:00.000Z

Orchestrator truncation check: `wc -l` = 553; `tail -20` ends on a complete final row of the §5 error table (`| ERR_INVALID_DATE_RANGE | 422 |`), a real section boundary — NOT truncated. Section headings present: §1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue. No regeneration needed.

Subagent summary (verbatim):

PRD complete and verified.

**Output:** `workspace/PRD.md` — **553 lines**, written incrementally in 11 appends; ends cleanly at the final row of the §5 error table with no audit footer.

**Sections**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Compliance Clock · 2.5 Record Identity, Timestamps and Record Versions · 2.6 Money, Basis Points and Rounding Discipline · 2.7 Stale-Version Guards on Authority-Displacing Writes · 2.8 Authority Intervals and the Half-Open Convention · 2.9 The Order of Rejection · 2.10 Nested Resource Retrieval · 2.11 Cascade Discipline
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Registering Originators, Filing State Licences and Establishing Sponsored Authority · 3.2 Continuing Education, Renewal Windows and Reinstatement · 3.3 Designing, Approving and Assigning Compensation Plans · 3.4 The Application Pipeline · 3.5 Closing a Loan, Provisional Accrual and Withheld Compensation · 3.6 Pricing Exceptions, Documented Justification and Concession Absorption · 3.7 The Commission Ledger · 3.8 Advertising Disclosure Review and Publication · 3.9 Examinations, Unlicensed Activity and the Nightly Compliance Epoch
- `## 4. Endpoint Definitions` — 4-column table, all 68 rows
- `## 5. Error Code Catalogue` — 2-column table, all 39 rows

**Coverage:** 14 entities, 9 state machines / 41 transitions, 2 OCC rules, 8 calculations (incl. all 5 divergent-variant pairs), 38 priority-ordered validations, 68 endpoints, 39 error codes, 7 roles — all rendered into prose. All 101 non-constant `UPPER_SNAKE` tokens in the scaffold (enum values, state names, audit event types, finding codes, error ids) appear verbatim; the only scaffold tokens absent are the 31 formula constant *names* (`TIER2_BPS`, `ABSORB_HIGH_PCT`, ...), which are rendered as their literal values in prose by design, plus the scaffold's own `ERR_XXX` placeholder.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 151 required, 151 present, 0 missing
- endpoints[].request_body: 90 required, 90 present, 0 missing
- endpoints[].query_params: 67 required, 67 present, 0 missing
- endpoints[].path_params: 1 required (id), 1 present, 0 missing
- structured output fields (authority / ce-compliance / reconciliation / sweep): 24 required, 24 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose (§2.9 ordered list + in-context prose), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (incl. pinned rounding/clamp orders and all variant divergences), 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 103 side-effect lines checked, 103 expressed, 0 missing
- entities[].fields[] structured content: 151 checked, 151 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (plan approve/reject, exception approve/deny, ad approve/reject, investigation substantiated/unsubstantiated, close branch A/B, licence surrender/revoke, CE attribution variants, accrual PROVISIONAL/FINAL), 8 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1143
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
(also verified: 0 unbackticked literal paths and 0 HTTP-method words anywhere in §§1–3)
Status: PASS
```

**Zero-Silence adjudications**
1. **`ERR_AD_DISCLOSURE_INCOMPLETE` scope conflict.** `validations[22].applies_to` names only the review-APPROVE action, but `errors[]` says "Approving or publishing". Rendered approval as the primary gate and additionally stated that publishing copy with non-empty recomputed findings carries the same code — lossless against both sources.
2. **Transitions whose `preconditions` widen the declared `from`.** Six cases (`ACTIVE→SURRENDERED` also from `RENEWAL_PENDING`; `ACTIVE→REVOKED` also from `RENEWAL_PENDING`/`EXPIRED`; `TAKEN→WITHDRAWN` also from `LOCKED`; `PUBLISHED→WITHDRAWN` also from `SUBMITTED`/`APPROVED`; `RESPONSE_SUBMITTED→CLOSED` also from `ESCALATED`; `OPEN→RESPONSE_SUBMITTED` also from `INFO_REQUESTED`) were rendered from the precondition set rather than the narrow `from` label.
3. **`LoanApplication.terminal_states` is `[WITHDRAWN]` only.** Rendered as declared, so `PAID_OFF` is explicitly *not* terminal (the compensation dimension keeps moving after payoff).
4. **`ERR_STALE_LICENSE_VERSION` at priority 10 covers two endpoints but one returns a different code.** The `applies_to` parenthetical says the plan-assignment endpoint returns `ERR_STALE_ORIGINATOR_VERSION`; rendered both as sharing one rejection slot in §2.9 with their distinct codes named.
5. **Cross-reference target drift after restructuring.** §3 was consolidated from 10 to 9 subsections (registration + sponsorship merged into 3.1) to stay inside the skill's 5–9 range; all 12 `§3.x` cross-references were remapped and re-verified against their intended targets.
6. **Four §4 descriptions corrected against the scaffold** after the initial draft asserted filters/semantics the scaffold does not have — most notably that `status-actions` supports SUSPEND (it does not; the `action` enum is `SURRENDER`/`REVOKE`/`REINSTATE`, and `LicenseRegistration` has no `SUSPENDED` state) and that `renewal-completions` reinstates expired licences (reinstatement is `status-actions` with `action = REINSTATE`). Ten list-endpoint filter descriptions were likewise corrected to the exact `query_params` sets. Also added the missing explicit `LOCKED → CLOSED` origination-dimension advance in §3.5.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-03T21:12:00.000Z

Orchestrator layout check: `test_helpers/` (9 modules) and `test_suite/` (20 files incl. conftest) are at the TASK ROOT; `find workspace -maxdepth 2 -name 'test_*' -type d` returned nothing, so no stray copies were written under workspace/.

Subagent summary (verbatim):

All seven Stage 2 partitions have landed and the full audit is green. Final state:

## Files written (all at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 2657 lines: `__init__.py` 10, `constants.py` 189, `types.py` 492, `api_errors.py` 92, `api_client.py` 369, `test_users.py` 90, `factories.py` 327, `assertions.py` 424, `fixtures.py` 664.

`test_suite/` — 8041 lines, `conftest.py` 63 + 19 test files:

| file | lines | tests | queue |
|---|---|---|---|
| test_01_ce_and_compensation_variant_divergence.py | 297 | 6 | A |
| test_02_reconciliation_and_concession_arithmetic.py | 296 | 6 | A |
| test_03_advertising_cycle_and_parallel_loan_dimensions.py | 325 | 6 | A |
| test_04_authority_lapse_and_clawback_cascades.py | 383 | 6 | A |
| test_05_rejection_order_between_competing_rules.py | 300 | 6 | A |
| test_06_exposure_and_ce_hour_boundaries.py | 329 | 6 | A |
| test_07_cross_entity_state_gating.py | 411 | 6 | A |
| test_08_sponsorship_and_assignment_interval_geometry.py | 346 | 6 | A |
| test_09_conserved_quantities_after_reversal.py | 375 | 6 | A |
| test_10_entity_creation_contracts.py | 363 | 7 | B |
| test_11_entity_reads_defaults_and_audit_shape.py | 267 | 6 | B |
| test_12_lifecycle_transitions_and_terminal_states.py | 429 | 8 | B |
| test_13_response_and_ledger_consistency.py | 443 | 6 | B |
| test_14_commission_and_exposure_arithmetic.py | 521 | 7 | B |
| test_15_business_rule_validation.py | 598 | 10 | B |
| test_16_authentication_authority_and_plan_errors.py | 594 | 9 | B |
| test_17_education_pricing_and_licence_errors.py | 637 | 8 | B |
| test_18_endpoint_surface_and_operator_actions.py | 492 | 6 | B |
| test_19_role_and_identity_gating.py | 572 | 6 | B |

## Coverage

- **127 tests total.** Queue A: 54 tests covering **18/18** non-stub difficulty instances (3 per instance). Queue B: 73 tests covering **60/60** non-stub corner instances.
- **Zero untranslated instances; zero skips**, and no `pytest.mark.skip`/`xfail` or placeholder anywhere.
- Every test carries exactly one `Design:` line as the last docstring line, resolving verbatim to a real non-stub instance; no dual or untagged tests. All 28 `excluded_because:` stubs left untranslated, and every stub's `difficulty_instance:` pointer was checked to resolve (no broken cross-references).
- All 39 catalogued error ids are exercised. Every test docstring carries at least one PRD citation; each agent byte-verified its quotes against `workspace/PRD.md`.

## Verification run

`ast.parse` + `pyflakes` clean on all 30 files (only the intentional `noqa` fixture re-exports in `conftest.py` flag); all 20 suite modules import with the task root on `PYTHONPATH`; no file mentions "scaffold"; every `api.*`, `factories.*`, `fixtures.*`, `assertions.*` and `ApiErrorId.*` reference statically confirmed to exist; no duplicate test names; every test parameter resolves to a real fixture. No pytest run and no server started (no implementation contact).

## Adjudications (PRD always wins over the design index)

1. **Plan assignment returns 200, not 201** (mine). PRD §4 gives 201 only to endpoints creating a brand-new record, and PRD §3.3 says the assignment response is the *updated originator*. Two agents flagged that `test_helpers/fixtures.assign_plan` pinned 201; I corrected it to 200 and tightened test_18's OCC replay to `validate_success` (200) instead of a lenient 2xx read.
2. **`FUNDED` → `CLOSED`** (test_13, test_19). Two design instances assert a `FUNDED` loan status; PRD §3.4/§3.5 enumerate `TAKEN/LOCKED/CLOSED/PAID_OFF/WITHDRAWN` and say close advances `LOCKED → CLOSED`. Tests assert `CLOSED`.
3. **Close-time ledger variant is `PROVISIONAL`/`ACCRUED`** (test_19), not the yaml's `FINAL`, per PRD §3.5.
4. **Sponsorship second relinquish** (test_12): PRD never declares `RELINQUISHED` terminal, so HTTP 409 is pinned exactly with the error id accepted as one of `ERR_ALREADY_TERMINAL`/`ERR_INVALID_STATE_TRANSITION`; all state assertions stay exact.
5. **Instant vs string equality**: several files use a local `_instant()` parser for server-computed timestamps other than `created_at`/`updated_at`, because PRD §2.5 pins three fractional digits only for the common fields while the design index wrote bare-second literals. The instant value is still asserted exactly.
6. **Post-revocation lock returns `ERR_LICENSE_NOT_ACTIVE`** (test_07), justified from §2.9 rule 13's precedence over rule 14.

## Sub-assertions deliberately dropped (instance still fully covered)

- Double-void of a CE credit → `ERR_ALREADY_TERMINAL` (PRD never declares CE `VOIDED` terminal).
- Cascade-opened investigation `detected_at` (PRD stamps it only on the manual route) and `restitution_cents == 0` at open (PRD fixes it only at finding time).
- `decided_by_user_id`/`decided_at` nullity on a cascade-withdrawn pricing exception.

## Step 6: Generate implementation — 2026-09-03T21:12:00.000Z

Subagent summary (verbatim):

The implementation is complete and verified. Smoke servers are shut down (only pids 1432194 / 1490123 on ports 18602 / 18777 were killed by pid; no pattern-kill was ever used) and all `__pycache__` dirs removed.

## Files written (root: `workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 99 |
| `db.py` | 97 |
| `errors.py` | 97 |
| `middleware.py` | 79 |
| `response.py` | 80 |
| `serializers.py` | 275 |
| `util.py` | 64 |
| `validators.py` | 173 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `routes/__init__.py` | 0 |
| `routes/common.py` | 85 |
| `routes/originators.py` | 223 |
| `routes/licenses.py` | 244 |
| `routes/sponsorships.py` | 46 |
| `routes/ce.py` | 155 |
| `routes/plans.py` | 176 |
| `routes/loans.py` | 273 |
| `routes/pricing.py` | 153 |
| `routes/comp_records.py` | 26 |
| `routes/ads.py` | 159 |
| `routes/exams.py` | 109 |
| `routes/investigations.py` | 110 |
| `routes/audit.py` | 20 |
| `routes/ops.py` | 30 |
| `services/__init__.py` | 0 |
| `services/audit.py` | 49 |
| `services/authority.py` | 147 |
| `services/calc.py` | 290 |
| `services/cascade.py` | 227 |
| `services/ce.py` | 117 |

**3614 lines total.** Every `.py` file passes `ast.parse`.

## Endpoints: 68 / 68

`app.url_map` enumerates exactly 68 distinct method+path pairs, matching the 68 declared endpoints (13 blueprints).

## Launcher

`start.sh` is executable, `cd`s to its own directory, installs Flask only if the import fails (an unconditional pip install causes boot contention across the 8 concurrent sweep rounds), then `exec python3 app.py`. `app.py` reads `int(os.environ.get("PORT", "10000"))` and calls `app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)` in the foreground. Verified live: `PORT=18777 ./start.sh` served `GET /originators` → 200.

## Storage / seeding

14 in-memory dicts on a single `Store` object; no SQLite, no disk, no `/tmp`. Confirmed on a fresh import that all 14 stores are empty and the logical clock is exactly `2026-08-01T00:00:00Z`. One global `RLock` is taken in `before_request` and released in `teardown_request`, so each request's mutation sequence is atomic.

## End-to-end verification

A ~60-call smoke run covered licensing → sponsorship → plan design/approval/assignment → loan take/lock/pricing-exception/close → PROVISIONAL vs FINAL reconciliation (`total_final_cents` 240000, `total_delta_cents` -10000) → payoff clawback (`days_held` 31, `recapture_pct` 100, `clawback_cents` 240000, `exposure_score` 53 from 12.5 + 15 + 25 rounded half-up) → CE course/credit/compliance → advertising submit/review/publish → examinations → the nightly three-part sweep (licence expired, sponsorship relinquished, inquiry escalated, plan unassigned) → audit trail `sequence_no` 1..9 with `SYSTEM`/null actor on the two cascade entries. A second round confirmed `ERR_CE_HOURS_INSUFFICIENT` 422, `ERR_STALE_LICENSE_VERSION` 412, `ERR_ALREADY_TERMINAL` 409, `ERR_LICENSE_NOT_ACTIVE` 422 post-revocation, `ERR_ORIGINATOR_IDENTITY_MISMATCH` 403, `ERR_INVALID_REQUEST` 400, `ERR_REFERENCED_RESOURCE_NOT_FOUND` 404, 405 on a bad method, plus `ERR_MISSING_AUTH_HEADERS` 401, `ERR_ROLE_NOT_PERMITTED` 403, `ERR_DUPLICATE_KEY` 409 and `ERR_INVALID_PAGINATION` 400 from round one.

## PRD-interpretation adjudications

- Priority-14 `ERR_STATE_NOT_AUTHORIZED` at take/lock excludes the sponsorship condition so priority 15 `ERR_SPONSORSHIP_REQUIRED` stays reachable, per §3.4's three-stage enumeration.
- Priority 4 (identity) on `POST /loan-applications` and `POST /advertisements` fires only when body `originator_id` is present as a string; absent/mistyped falls to priority 7. For path-based ownership the path row resolves first, so a bad path id yields 404 before the identity check.
- Terminal-state check precedes invalid-transition, since §2.9 item 11 scopes itself to non-terminal invalid-source cases.
- `authority_flag != VERIFIED` at lock → `ERR_INVALID_STATE_TRANSITION` (no dedicated code exists).
- Close with `funded_at` outside the plan's CLOSED assignment interval → `ERR_PLAN_NOT_ACTIVE`.
- Filing a pricing exception against a non-LOCKED loan, or approving one whose loan left LOCKED → `ERR_INVALID_STATE_TRANSITION`.
- Licence activation with `employment_status != EMPLOYED` or `clock >= expiration_date`, and reinstatement with `employment_status != EMPLOYED` → `ERR_INVALID_STATE_TRANSITION`; for reinstatement that employment test runs last (after 33 CE and 37 limit) to match §3.2's order.
- Date coherence not in `ERR_INVALID_DATE_RANGE`'s catalogue (licence `expiration_date`/`renewal_window_opens_at`, plan `max_fee_cents >= min_fee_cents`, inquiry `response_due_at > clock`) → `ERR_INVALID_REQUEST` 400; that code is reserved for plan assignment, CE credit filing and payoff.
- Renewal completion recomputes CE with the MAKEUP variant *before* the CE gate, then rolls expiration/window +365d, `ce_reporting_year += 1`, and recomputes again.
- CE course rescission voids every APPLIED credit first, then re-tests suppression restoration, so successive-year suppression is only re-evaluated once all voided rows have left APPLIED.
- `days_held`/`recapture_pct` are written on the FINAL+RECONCILED line on every payoff, even at 0% recapture; ACCRUED lines untouched.
- Audit events are emitted only where the PRD states them: none on a first non-superseding sponsorship claim, CE course rescission, manual investigation opening, ad submissions/revisions/publish, or remediation; `PLAN_APPROVED` on assignment only when a prior ACTIVE plan is superseded; `MONITORING_ESCALATED` only in the payoff cascade.
- Derived read-time fields (`authorized_state_codes`, the three ledger totals, `open_investigation_count`) never bump a row's `version` on their own.
- `note_rate_bps`/`locked_amount_cents`/`funded_amount_cents` validate as integers `>= 0` only (no scaffold ranges); free-text notes carry no minimum length.
- `Fraction` arithmetic throughout with one explicit `round_half_up` at each pinned rounding point (round-per-line-then-sum for commission roll-up; round-once for exposure score).

## Step 7: Run tests and iterate — 2026-09-03T21:35:00.000Z

Orchestrator verification (independent of the subagent's claim, per the known failure mode where a Step 7 agent reports a clean sweep with no artifacts): all 8 `workspace/implementation/results.{1..8}.json` exist, each `passed == total == 127`, `failed == 0`.

Subagent summary (verbatim):

Clean sweep: all 8 parallel rounds passed 127/127.

## Summary

**Iterations run:** 2 (iteration 1: 49 failures identical in all 8 rounds; iteration 2: 8/8 rounds green at 127/127). No flakiness observed — failures were fully deterministic, and results files for the final sweep are left at `workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and was uniquely derivable, so all 49 were fixed rather than removed.

**Fixes applied to `test_suite/`** (2 files, 7 call sites — one bug, repeated):
- `test_suite/test_14_commission_and_exposure_arithmetic.py` (lines 218, 249) and `test_suite/test_15_business_rule_validation.py` (lines 134, 142, ~367, 447, ~594): removed the double-unwrap `validate_success(...)["data"]`. The runner's `validate_success` already returns the envelope's `data` payload, so the extra subscript raised `KeyError: 'data'` before any assertion could run. This is a test-authoring bug, not a contract change — every surviving assertion is unchanged.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**
- `routes/originators.py`, `assign_plan()`: returned `created(...)` (HTTP 201) for `POST /originators/{id}/compensation-plan-assignments`; changed to `ok(...)` (HTTP 200). PRD §4 says 201 is only for "endpoints that bring a brand-new record into existence" and §3.3 says "The response to an assignment is the updated originator record" — no new row is minted, so 200 is required. This single defect was the upstream setup failure behind 42 of the 49 failures (`fixtures.assign_plan` asserts `expected_status=200`).
- `routes/loans.py`, `lock_application()`: moved the `authority_flag != "VERIFIED"` precondition to *after* the `authority_probe` re-verification. PRD §2.9 numbers the licence-active/state-authorised/sponsorship-covered checks as rules 13–15 and says explicitly they are "Checked when taking and when locking an application", while the `authority_flag` gate of §3.4 appears nowhere in the fixed order and is assigned no error code. So on a lock after the owning licence was revoked, `ERR_LICENSE_NOT_ACTIVE` must answer. The PRD-required `authority_flag` check is preserved (still `ERR_INVALID_STATE_TRANSITION`), just demoted below the numbered rules so it only fires on the residual case where the flag is stale but authority is otherwise intact.

## Step 8: Finalize PRD — 2026-09-03T21:42:00.000Z

Step 8 was NOT skipped: Step 7 applied 2 `implementation/` fixes and 7 `test_suite/` call-site fixes, so the skip condition (zero iterations beyond baseline) did not hold.

Subagent summary (verbatim):

Done. Wrote `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 553 lines / 113,414 bytes
- PRD_FINALIZED.md: 553 lines / 114,265 bytes
- Line delta: 0 (+0.0%); byte delta +851 (+0.75%). Both edits are inline revisions to existing paragraphs; no new sections, no reordering.

## Changes
- **§3.4 (Application Pipeline, lock paragraph, PRD line 296)** — revise — moved the `authority_flag == VERIFIED` precondition behind the from-scratch authority re-verification, and pinned it: the flag check is *not* one of §2.9's numbered rules, is evaluated after rules 13–15, so a lock after the owning licence was revoked answers `ERR_LICENSE_NOT_ACTIVE` (even though the lapse cascade has already set the flag to `SUSPENDED`); the flag failure decides the response only when authority is otherwise intact and is then `ERR_INVALID_STATE_TRANSITION` (HTTP 409). — `implementation/routes/loans.py:134-144`
- **§3.3 (Compensation Plans, assignment paragraph, PRD line 282)** — insert — appended that the plan assignment mints no new row and so returns HTTP 200 under §4, not 201. — `implementation/routes/originators.py:151-168`

No PRD edit for the `test_suite/` double-unwrap fixes (`test_14` lines 218/249, `test_15` lines 134/142/367/447/594): that was a test-authoring bug against the runner's `validate_success` contract, revealing no PRD silence or mismatch.

## Per-edit pre-edit search log

**Edit 1 — §3.4 lock ordering**
- (a) Subject: the loan's `authority_flag` as a precondition/branch input, and the relative order of the lock endpoint's preconditions.
- (b) Paths enumerated (grepped `authority_flag` across all of `implementation/`, then read each hit): `routes/loans.py:99` (intake initialises `VERIFIED`), `routes/loans.py:128-151` (`lock_application` — the Step 7 site: `gate(...TAKEN)` → `authority.authority_probe` → flag check), `routes/loans.py:204` (close forks Branch A/B on the flag — a *fork*, never a rejection), `routes/loans.py:268` (release sets flag back to `VERIFIED`), `routes/investigations.py:83,108` (finding sets `UNAUTHORIZED`/`VERIFIED`), `services/cascade.py:65` (lapse cascade sets `SUSPENDED`), `serializers.py:161`; plus `services/authority.py` (`authority_probe` fixed order 13→14→15, `publish_authority_probe` — the ad-publish path consults no flag), `routes/common.py` `gate()` (rules 11/12), `errors.py:15` (409). Also checked `test_suite/test_07_cross_entity_state_gating.py:166-210` as corroborating evidence of the observable ordering.
- (c) Adjustments made to stay consistent with all of them: scoped every new clause to *locking* only, so the close-time fork (Branch A/B on the same field) and the release/finding/cascade writers are untouched; said the flag precondition "is evaluated after the re-verification" rather than any claim about where flag checks sit generally; kept "not one of the numbered rules of §2.9" so §2.9 rule 11 ("every non-terminal invalid-source case") is not contradicted — the source `status` is still `TAKEN` in this case; used "only where authority is otherwise intact at the current instant and the flag alone is not `VERIFIED`" rather than naming `SUSPENDED`/`UNAUTHORIZED`, since the impl tests `!= "VERIFIED"`.

**Edit 2 — §3.3 assignment HTTP status**
- (a) Subject: the success HTTP status of `POST /originators/{id}/compensation-plan-assignments`, and by implication §4's 201-vs-200 rule.
- (b) Paths enumerated: `routes/originators.py:112-168` (`assign_plan` — writes assignment fields onto the existing plan, supersedes the prior plan, sets `originator.compensation_plan_id`, returns `ok(...)`); every `created(` callsite in `implementation/routes/` (`investigations.py:44`, `originators.py:43`, `exams.py:50`, `ads.py:49`, `loans.py:107`, `pricing.py:65`, `plans.py:84`, `plans.py:129`, `ce.py:42`, `ce.py:121`, `licenses.py:73`, `licenses.py:244`) — all twelve genuinely insert a new row, so the §4 rule as written stays true; `response.py:27` (`ok` defaults to 200); the other `ok(...)` returns in `routes/originators.py` (58, 70, 78, 98, 168, 219).
- (c) Adjustment: phrased the addition as an instance of §4's existing rule ("one of the state-advancing actions that return HTTP 200 under §4") rather than as a new or special-case rule, so no other endpoint's status is narrowed or re-specified; justified it by the observable fact that no row is created, which holds against all twelve `created()` sites.

## Step 9: Complete PRD — 2026-09-03T21:50:09.991Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as THREE SEQUENTIAL file-partitioned passes over `implementation/` rather than one monolithic pass. Rationale — a single Step 9 subagent facing a 30-file / 3614-line implementation routinely under-scans and exits leaving `PRD_COMPLETED.md` byte-identical to its source, i.e. the scan never really ran. Partitioning by implementation file makes each pass's scope small enough to walk exhaustively, and running them sequentially (each editing the same PRD_COMPLETED.md in place, later passes told not to re-copy or re-litigate earlier edits) keeps the document single-writer at all times.

Partition: pass 1 = cross-cutting + originators/licences/sponsorships/audit/authority (15 files); pass 2 = ce/plans/loans/pricing/comp_records + calc/ce services (7 files); pass 3 = ads/exams/investigations/ops + cascade (5 files). Every `.py` file under `workspace/implementation/` was covered exactly once.

Verification: `PRD_FINALIZED.md` 553 lines / 114,265 chars → `PRD_COMPLETED.md` 553 lines / 130,723 chars (+16,458 chars); `diff` reports 61 changed lines (122 diff lines), so the file is emphatically NOT byte-identical to its source. Tail ends at the last row of the §5 error table (`| ERR_INVALID_DATE_RANGE | 422 |`) — a real section boundary — and all 5 top-level sections survive. `find` confirms no `.py` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the passing sweep's `results.1.json`, so the green 8×127/127 result still describes the shipped code.

Totals across the three passes: **66 edits — 55 ambiguity-pins, 11 mismatch-revisions**, all in-paragraph (0 line-count change, no new sections).

### Pass 1 summary (verbatim)

PASS 1 complete. `PRD_COMPLETED.md` created from `PRD_FINALIZED.md` and edited in place with 26 surgical single-line edits (no new sections, no whole-file rewrite).

**Line counts / delta:** PRD_FINALIZED.md 553 lines / 114,265 chars → PRD_COMPLETED.md 553 lines / 120,102 chars (**+5,837 chars**, 26 lines revised).

**Counts:** 20 ambiguity-pins, 6 mismatch-revisions.

**Changes**
- §2.1 — insert — ambiguity — auth headers are trimmed before every comparison, so whitespace-only counts as empty — `middleware.py:31-34`
- §2.1 — insert — ambiguity — originator body-identity check applies only when `originator_id` is present as a string, else falls through to `ERR_INVALID_REQUEST` — `middleware.py:68-79`
- §2.1 — insert — ambiguity — the entry for the caller's own directly-requested mutation carries the caller's role even when it drives a cascade (revoke's `LICENSE_STATUS_CHANGED` is not `SYSTEM`) — `licenses.py:178`, `services/audit.py:32-35`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `util.py:16-17`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one value taken from real server time, not the logical clock — `response.py:20`, `util.py:51`
- §2.3 — insert — ambiguity — "integer" for `limit`/`offset` = digits with optional sign, whitespace tolerated — `response.py:14,55-63`
- §2.3 — insert — ambiguity — `created_at` ties broken by server write sequence, never by id — `db.py:95-97`
- §2.5 — revise — **mismatch** — audit `detail` is a structured JSON object (`{}` when nothing supplied), not a one-line prose summary — `services/audit.py:43`
- §2.8 — insert — ambiguity — supplied instants are truncated down to whole milliseconds at parse time and stored/echoed truncated — `util.py:36-37`
- §2.9 r7 — insert — ambiguity — declared non-filter query params validated here; body must be a JSON object when any field is declared; JSON `null` == absent; booleans rejected for integers; undeclared fields ignored — `validators.py:14-31,46-47,72`
- §2.10 — insert — ambiguity — filters are unvalidated exact-equality matches (bad value ⇒ empty page, not an error); unknown params ignored — `routes/common.py:57-80`
- §2.11 — revise — **mismatch** — a row is refreshed at most once per request (multi-hop cascade moves `version` by exactly one; rows created by the request stay at `version` 1) — `db.py:76-92`
- §3.1 — insert — ambiguity — `hire_date` accepts any parseable instant, no clock constraint — `originators.py:28`
- §3.1 — revise — **mismatch** — PATCH accepts only `employment_status`, required, no transition gate, other fields ignored — `originators.py:61-70`
- §3.1 — insert — ambiguity — licence-filing date-coherence violations report `ERR_INVALID_REQUEST` (400), not `ERR_INVALID_DATE_RANGE` — `licenses.py:45-48`
- §3.1 — insert — ambiguity — activation's employment and not-yet-expired conditions both report `ERR_INVALID_STATE_TRANSITION`, employment first — `licenses.py:97-100`
- §3.1 — insert — ambiguity — a sponsorship claim places no precondition on the licence's `status` (incl. `PENDING`/terminal) — `licenses.py:203-222`
- §3.1 — revise — **mismatch** — relinquishment requires only that the row is `ACTIVE`; the owning licence's status is not examined — `sponsorships.py:32-33`
- §3.1 — insert — ambiguity — status-action `note` is capped at 2000 chars and is carried into the audit `detail` — `licenses.py:155-158`
- §3.2 — revise — ambiguity — reinstatement check order and codes: stored `ce_satisfied` false ⇒ `ERR_CE_HOURS_INSUFFICIENT` before the count limit; non-`EMPLOYED` owner ⇒ `ERR_INVALID_STATE_TRANSITION` — `licenses.py:181-188`
- §3.7 — revise — **mismatch** — reconciliation rewrites the loan's line whose `status` is `ACCRUED`; a loan with no such line (or unresolvable plan) is skipped silently, uncounted — `originators.py:186-195`
- §3.7 — insert — ambiguity — an empty reconciliation run returns zeros/empty ids and still bumps the originator's `version` (unconditional exposure recompute) — `originators.py:217-218`
- §3.8 — insert — ambiguity — ad licence selection tie on `created_at` goes to the later-written row — `services/authority.py:137-138`
- §4 — insert — ambiguity — trailing slash is not significant in path matching — `app.py:19`
- §4 table — revise — **mismatch** — PATCH /originators/{id} description narrowed to employment status — `originators.py:61-70`
- §5 — insert — ambiguity — unrouted path ⇒ `ERR_RESOURCE_NOT_FOUND` 404; unsupported method ⇒ `ERR_INVALID_REQUEST` with HTTP 405 (only status deviation from the table) — `app.py:65-74`

Deliberately left to later passes (sourced outside my partition): `services/calc.py` / `services/ce.py` derivations reached via the CE-compliance read, and `services/cascade.py` hop/`SYSTEM`-attribution details.

### Pass 2 summary (verbatim)

Pass 2 complete. All seven partition files were walked endpoint-by-endpoint and formula-by-formula against the PRD; 17 in-paragraph edits were made with the Edit tool (no new sections, no line-count change, Pass 1's edits untouched).

**Size:** 553 lines / 120,102 chars → 553 lines / 124,098 chars (+3,996 chars, all in-paragraph).

**Counts:** 15 ambiguity-pins, 2 mismatch-revisions.

**Changes**
- §2.10 — revise — mismatch — the CE-credit `attributed_year` filter is parsed as a decimal integer and compared to the stored integer rather than by string equality (an unparseable value matching nothing) — `routes/ce.py:129`, `routes/common.py:67`
- §3.2 (provider rescission) — revise — ambiguity+mismatch — rescinding an already-`RESCINDED` course is accepted; "every affected licence" pinned as every licence of every originator whose credit was voided, whatever that licence's own `status`; a rescission appends no audit entry at all — `routes/ce.py:47-69`, `services/ce.py:79`
- §3.2 (filing a credit) — insert — ambiguity — a successful filing recomputes CE on every licence of that originator regardless of licence `status` — `routes/ce.py:120`
- §3.2 (counted set) — insert — ambiguity — a recompute whose result equals the stored values writes nothing, so the licence's `updated_at`/`version` do not move — `services/ce.py:72-75`
- §3.2 (computed CE read) — insert — ambiguity — `reporting_year` default tie-break (later-written row) and fallback to the logical clock's calendar year when no licence exists; the read's `ce_satisfied` compares against the `required_ce_hours` of that same greatest-`created_at` licence (8 when none), independent of the year evaluated — `services/ce.py:100-117`
- §3.2 (voiding) — insert — ambiguity — no precondition on `credit_status`; an `EXCLUDED_SUCCESSIVE_YEAR` or already-`VOIDED` credit may be voided, overwriting `void_reason` — `routes/ce.py:142-146`
- §3.2 (renewal completion) — revise — ambiguity — "counted toward the reporting year" pinned as `attributed_year` equal to `ce_reporting_year` — `services/ce.py:87-97`
- §3.3 (drafting) — insert — ambiguity — `max_fee_cents` below `min_fee_cents` is `ERR_INVALID_REQUEST` (400), checked after all single-field checks — `routes/plans.py:65`
- §3.3 (pay variables) — insert — ambiguity — declaration requires `DRAFT`: `ACTIVE` → `ERR_INVALID_STATE_TRANSITION`, terminal → `ERR_ALREADY_TERMINAL` — `routes/plans.py:110`
- §3.3 (approval fork) — insert — ambiguity — plan-decision `note` capped at 2,000 characters — `routes/plans.py:147`
- §3.4 (locking) — insert — ambiguity — `note_rate_bps` and `locked_amount_cents` are required integers ≥ 0 and do not carry the intake bounds — `routes/loans.py:132-133`
- §3.5 (closing) — insert — ambiguity — `funded_amount_cents`, `lender_paid_comp_cents`, `borrower_paid_comp_cents` required integers ≥ 0 with no ceiling — `routes/loans.py:159-162`
- §3.5 (closing) — insert — ambiguity — a `funded_at` outside the assignment interval, or a plan with no interval, reports `ERR_PLAN_NOT_ACTIVE` — `routes/loans.py:182-183`
- §3.5 (per-line commission) — insert — ambiguity — with several `APPROVED` exceptions on a loan the earliest by `created_at` is read; `accrued_cents` is not floored at zero — `services/calc.py:126-151`
- §3.5 (compensation release) — insert — ambiguity — loan `status` gated first: `WITHDRAWN` → `ERR_ALREADY_TERMINAL`; `TAKEN`/`LOCKED` or a non-`PENDING` `compensation_status` → `ERR_INVALID_STATE_TRANSITION` — `routes/loans.py:255-257`
- §3.6 (filing) — insert — ambiguity — non-`LOCKED` loan → `ERR_INVALID_STATE_TRANSITION`, `WITHDRAWN` → `ERR_ALREADY_TERMINAL`, both ahead of the justification/cap gates — `routes/pricing.py:41`
- §3.6 (deciding) — insert — ambiguity — `decision_note` required, 1–2,000 chars; `second_approver_user_id` ≤ 64 chars; approval on a non-`LOCKED` (including `WITHDRAWN`) loan → `ERR_INVALID_STATE_TRANSITION`; an empty/whitespace-only second approver counts as missing — `routes/pricing.py:89-120`

**No change needed** (already uniquely pinned): the volume-tier adder and its clamp order, per-line and pre-absorption commission arithmetic, the five concession-absorption steps, clawback day/percentage arithmetic, the four exposure terms with single-rounding and the 60 threshold, provisional vs final variant inputs, CE attribution and successive-year suppression, the plan approval/rejection forks and §2.9 precedences, and the `compensation-records` read filters.

### Pass 3 summary (verbatim)

Pass 3 complete. All five partition files walked exhaustively; PRD_COMPLETED.md edited in place only (no re-copy, no new sections, no line-count change).

**Size:** 553 lines / 124,098 chars → 553 lines / 130,723 chars (+6,625 chars, 23 in-paragraph changes across 24 Edit calls; one call was a tightening of my own publish wording).

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions.

**Changes**
- §3.8 ¶1 — insert — ambiguity — `disclosed_nmls_ids`/`disclosed_license_numbers` are unconstrained string arrays (no count/format check); `target_state_codes` stored as supplied, unsorted and un-deduped — routes/ads.py:34-43
- §3.8 submission ¶ — insert — ambiguity — submission appends no audit entry — routes/ads.py:69-76
- §3.8 review ¶ — insert — ambiguity — `note` ≤2000 chars; recomputed findings are written to the row before either branch, so a refused approval keeps them while `status`/`reviewed_by_user_id`/`updated_at`/`version` stand — routes/ads.py:85-91
- §3.8 review ¶ — insert — ambiguity — `AD_DECIDED` detail = decision, resulting status, recomputed findings, plus note when supplied — routes/ads.py:95-99
- §3.8 revision ¶ — insert — ambiguity — omitted arrays leave prior lists untouched; `content_text` bounded as at drafting; `medium`/`target_state_codes` not revisable — routes/ads.py:109-119
- §3.8 publication ¶ — insert — ambiguity — authority probe precedes the inspection (so a double failure reports `ERR_STATE_NOT_AUTHORIZED` and leaves findings untouched); findings persist on a refused publish; no declared input; no audit entry; `reviewed_by_user_id` retained — routes/ads.py:130-143
- §3.8 withdrawal ¶ — insert — ambiguity — optional body, `reason` ≤2000, detail = `status` + `reason`, no re-inspection, no `reviewed_by_user_id` stamp, DRAFT/REJECTED → `ERR_INVALID_STATE_TRANSITION` — routes/ads.py:150-158
- §3.9 inquiry ¶ — insert — ambiguity — a `response_due_at` at or before the clock is `ERR_INVALID_REQUEST` (not `ERR_INVALID_DATE_RANGE`) and is checked ahead of `exam_reference` uniqueness; a non-string `originator_id` is treated as absent — routes/exams.py:32-40
- §3.9 responses ¶ — insert — ambiguity — `narrative` required, ≤8000 chars, no minimum — routes/exams.py:73
- §3.9 info-request ¶ — insert — ambiguity — `request_note` required, ≤8000 chars — routes/exams.py:90
- §3.9 investigations ¶ — revise — mismatch — no precondition on the named loan's status; `open_investigation_count` is derived on read so the opening writes nothing to the originator row (no version move); manual opens append no `INVESTIGATION_OPENED` — routes/investigations.py:32-44
- §3.9 findings ¶ — insert — ambiguity — `restitution_cents` required integer ≥0, no ceiling — routes/investigations.py:68
- §3.9 findings ¶ — revise — mismatch — count recompute is a derived read (originator version unmoved); `INVESTIGATION_FINDING` detail = finding, restitution_cents, loan_application_id — routes/investigations.py:78-90
- §3.9 remediation ¶ — insert — ambiguity — `remediation_note` ≤8000; loan version moves; derived count; no audit entry — routes/investigations.py:99-109
- §3.9 sweep ¶ (first sweep) — insert — ambiguity — licence entry detail = `status EXPIRED` + `reason SWEEP_EXPIRY`, investigation entry detail keys, all entries `actor_role SYSTEM` with null actor — services/cascade.py:87-95,191-192
- §3.9 sweep ¶ (second/third) — insert — ambiguity — plans/inquiries examined in `created_at` order; clearing only when the originator still points at that plan (null assignee / re-pointed / missing originator skipped); plan row left wholly untouched; neither sweep appends audit — services/cascade.py:197-225
- §3.9 sweep report ¶ — insert — ambiguity — lists follow processing order, `unassigned_originator_ids` deduped, and a same-instant re-run is idempotent (all six lists empty) — services/cascade.py:171-227
- §2.4 — insert — ambiguity — `to_iso8601` required, any parseable instant including one earlier than the current setting; response data carries only `current_utc` — routes/ops.py:17-22
- §2.11 — insert — ambiguity — a null `funded_at` sorts ahead of any set one in cascade loan ordering — services/cascade.py:13
- §3.1 cascade hop 5 — revise — mismatch — hop 5 is a derived read, landing no write on the originator row — services/cascade.py:83
- §3.7 recapture ¶ — insert — ambiguity — an un-reconciled `ACCRUED` line is left wholly alone (null `days_held`/`recapture_pct`, no exposure recompute); on a reconciled line `days_held`/`recapture_pct` are written and its version moves even when `recapture_pct` is 0, after which nothing else happens — services/cascade.py:125-131
- §3.7 clawback hop 5 — insert — ambiguity — exceptions visited in `created_at` order; one already carrying `true` is left untouched — services/cascade.py:157-161
- §3.7 clawback audit ¶ — insert — ambiguity — `COMP_CLAWED_BACK` subject/detail keys, `MONITORING_ESCALATED` appended after hop 5 with score/status detail, both `SYSTEM`-attributed with null actor — services/cascade.py:144-165

**Document sanity:** file still ends at the §5 error-code table's last row (`ERR_INVALID_DATE_RANGE | 422`), a real section boundary; every paragraph I touched re-read cleanly with no mangled splice, and no earlier pass's wording was reverted.

## Pipeline complete — 2026-09-03T21:50:09.991Z

All nine steps done. Final artifact set: SCAFFOLD.yaml (3700) + SCAFFOLD_DIFFICULTY_DESIGN.yaml (2026) + SCAFFOLD_CORNER_DESIGN.yaml (4916); test_helpers/ (9 modules, 2657 lines) + test_suite/ (conftest + 19 files, 8041 lines, 127 tests); workspace/{INSTRUCTION.md, PRD.md 553L, PRD_FINALIZED.md 553L, PRD_COMPLETED.md 553L} and workspace/implementation/ (30 files, 3614 lines, 68/68 endpoints) with results.{1..8}.json all at 127/127 passed, 0 failed.
