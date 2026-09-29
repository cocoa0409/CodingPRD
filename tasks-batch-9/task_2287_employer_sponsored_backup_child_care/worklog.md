# Worklog — task_2287_employer_sponsored_backup_child_care

## Step 1: Create task directory — 2026-09-01T14:45:51.549Z

Created `tasks/task_2287_employer_sponsored_backup_child_care/` and `tasks/task_2287_employer_sponsored_backup_child_care/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T16:33:53.608Z

All three artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2287_employer_sponsored_backup_child_care/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (top keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles). No `scaffold_difficulty_design` / `scaffold_corner_design` key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`.

**§1.0–§1.7 counts** — 13 entities; 7 state machines (Reservation carries parallel `fulfillment_status` × `billing_status` dimensions, Provider.network_status is cyclic); 2 OCC concurrency rules; 12 calculations (2 dual-variant); 53 ordered validations; 65 endpoints; 70 error codes; 5 peer roles. `api_prefix: /backup-care`, `difficulty_level: expert_plus`, complexity layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; consistency_model immediate; logical clock pinned via `POST /backup-care/_clock/set_current_utc` (forward-only).

**§1.8** — all 9 required rule_ids, 19 instances (≥2 each), every one with a full `setup` / `setup_api_calls` / `trigger` / `assert` recipe and pre-computed literals derived from the §1.3 formulas (e.g. in-home billable hours `max(plan_min, ceil(raw/0.25)*0.25)` → days `ceil(h/8)`, invoice `admin_fee = round_half_up(subtotal × 0.085)`).

**§1.9** — all 9 taxonomy sections of `references/claim-extraction-guide.md`, 67 instances: entities 12, state_machines 12, calculations 11, validations 8, endpoints 6, errors 7, rbac 5, complexity_layers 5, consistency_model 1. 45 carry full recipes; 22 are `excluded_because` stubs, each pointing at a real §1.8 instance name (verified programmatically — no dangling refs). Names are unique across both design files; every `${var}` is bound by an earlier `captures:`; call objects carry only `call`/`payload`/`as`/`as_user_id`/`captures`.

**Linter** — `scaffold_lint.py`: VERDICT clean, 1058 calls scanned across §1.8+§1.9, all §1.1 FKs reverse-reachable in §1.5.

**Coverage-audit notes**
- Every §1.6 code is now reachable. Families were routed deliberately: 404s via a 8-call not-found battery; state/terminal pairs via network- and commercial-domain batteries; temporal codes (clock rewind, block midnight/overlap, check-in/no-show/actual-window, offer expiry) via a temporal battery; confirm guards (window-outside-block, duplicate care date, same-day unavailable, not-in-network, offer-not-selected, overage-not-permitted) via a confirm-guard battery; the two 412 stale-version codes via the complexity_layers OCC corners; the four auth codes via the rbac section.
- Three fixes were needed to keep the catalog honest during authoring: rule 400 now explicitly stands down for terminal states (otherwise every `ERR_<ENTITY>_TERMINAL` was unreachable); three provably unconstructible codes were deleted (`ERR_CREDENTIAL_STATE_INVALID`, `ERR_RESERVATION_IN_SERVICE`, `ERR_RESERVATION_EMPLOYER_MISMATCH`); and three orphan codes were given §1.4 rows (`ERR_TOO_MANY_DEPENDENTS` @902, `ERR_EMPLOYER_CONTRACT_INACTIVE` @417, `ERR_PROVIDER_FIELD_IMMUTABLE` @423, with the PATCH-provider input widened so 423 is triggerable).
- Two priority races are asserted as such rather than left implicit: 417 beats 830 when activating a DRAFT plan under a TERMINATED employer, and 210 beats 230 when a provider_manager PATCHes a provider it does own.
- No sibling task directory was read, listed, globbed or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T16:33:53.608Z

Copied `./INSTRUCTION.md` → `tasks/task_2287_employer_sponsored_backup_child_care/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:49:15.488Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2287_employer_sponsored_backup_child_care/workspace/PRD.md` — **421 lines**, generated solely from `SCAFFOLD.yaml`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Structure
- **§1 Introduction** — 3 paragraphs from the scenario; states the `/backup-care` mount.
- **§2 Global Specifications** — 11 subsections: 2.1 the five peer roles and per-role identity binding (`ERR_UNAUTHENTICATED` / `ERR_UNAUTHORIZED` / `ERR_FORBIDDEN_SCOPE` distinctions); 2.2 the fixed response-structure block (verified byte-identical to `section-2.2-response-structure.md`); 2.3 pagination plus the four ordering overrides; 2.4 the logical clock (default `2026-08-01T00:00:00Z`, forward-only, recompute set); 2.5 `id`/`created_at`/`updated_at`/`version` and the explicit statement that `UsageLedgerEntry` and `InvoiceLine` carry only `id` and `created_at`; 2.6 both OCC guards; 2.7 rounding discipline (round-half-up, per-line-then-sum); 2.8 the full validation precedence as ten ordered bands with per-band internal ordering and `applies_to` enumerations; 2.9 the two parallel reservation dimensions; 2.10 the three conservation invariants; 2.11 benefit-year windowing.
- **§3 Business Logic** — 9 domain subsections covering employers/plan supersession, enrolment and dependents, the provider network (credentialing, posture machine, withdrawal cascade, capacity, both admission semantics), intake and plan pinning, ranking and the offer cycle, confirmation and the six-step entitlement waterfall, delivery outcomes, QA and the two score variants, invoicing/analytics/nightly sweep.
- **§4** — intro paragraph on 201-vs-200 plus a 65-row table. **§5** — 70-row error table. Document ends at §5 with no footer.

## Audit results (chat-only, not written to any file)
- **Contract 1 — Field-Name Coverage: PASS.** All 13 entities' fields present verbatim in backticks (0 missing); all endpoint `input`/`output` field names present (0 missing); all 5 role names; all 70 error codes.
- **Contract 2 — Rule Coverage: PASS.** All 51 validations with their exact `applies_to` endpoint sets; all 51 transitions across the 7 state machines (including both `CONFIRMED → NO_SHOW` triggers, the `CONFIRMED → MATCHING` withdrawal cascade, and the disjoint substantiate/dismiss sibling branches); both OCC rules with endpoint + field + error + 412; all 12 calculations translated with reconstructable arithmetic and every constant.
- **Contract 3 — §3 Path Purity: PASS.** 0 `/`-leading tokens, 0 bare HTTP methods, 0 method+path backticks in §3 (lines 147–275).
- Cross-checks: 65/65 endpoints match scaffold method+path exactly with **zero role-list mismatches**; 70/70 error codes match scaffold HTTP statuses exactly; no fuzzy quantifiers.

Three precision notes where the scaffold was silent and the PRD makes a determinate choice so tests have something to bind to: the stale-version guard is specified to fire immediately after existence resolution and before all state/temporal/capacity checks; the 14-hour care-window cap is attributed to `ERR_INVALID_WINDOW` (it has no dedicated code); and the "invoice may not be issued while a billed reservation is still `IN_SERVICE`" precondition is stated without naming an error code, since the scaffold declares none.

## Step 5: Generate unit tests — 2026-09-01T18:09:53.998Z

The suite is complete.

## Files written

Base: `/home/ubuntu/github/CodingPRD/tasks/task_2287_employer_sponsored_backup_child_care/`

**Stage 1 — `test_helpers/` (9 modules)**: `__init__.py` (flat re-export surface), `api_client.py`, `api_errors.py` (`ApiErrorId` + status map), `assertions.py` (entity shapes, invoice/ledger/report invariants, `round_half_up`, `ceil_to_quarter_hour`, rank-score helpers), `constants.py`, `factories.py`, `fixtures.py` (tiered world builders up to `setup_matchable_world` / `setup_confirmed_reservation` / `setup_issued_invoice` / `substantiated_incident`), `test_users.py`, `types.py`.

**Stage 2 — `test_suite/` (12 modules + `conftest.py`), 98 tests**

| file | tests |
|---|---|
| test_01_employer_and_benefit_plan_administration.py | 11 |
| test_02_employee_dependents_and_intake_gates.py | 7 |
| test_03_provider_network_and_credentialing.py | 8 |
| test_04_reservation_intake_and_state_guards.py | 10 |
| test_05_matching_and_offer_ranking.py | 9 |
| test_06_confirmation_capacity_and_guards.py | 11 |
| test_07_in_home_hours_and_day_charges.py | 5 |
| test_08_overage_tiering_and_entitlement.py | 6 |
| test_09_cancellation_and_no_show_penalties.py | 7 |
| test_10_provider_withdrawal_and_maintenance.py | 6 |
| test_11_incident_reports_and_quality_scoring.py | 8 |
| test_12_invoicing_settlement_and_reporting.py | 10 |

## Queue coverage

- Queue A (difficulty): **50 tests** over **19/19** instances, every instance carrying ≥2 tests, across all nine rule_ids.
- Queue B (corner): **48 tests** over **45/45** non-stub instances (22 stub instances in the yaml were correctly not translated).
- Every test docstring ends in exactly one verbatim `Design:` line; a mechanical audit resolves all 64 distinct tags against the two yamls and greps every quoted citation (≥8 words, whitespace-normalized) against `workspace/PRD.md` — zero problems. `pyflakes` clean, `compileall` clean. No test run was possible (no API server in this environment).

## Instances skipped or trimmed, with reason

- **22 queue-B stub instances** — marked stub in `SCAFFOLD_CORNER_DESIGN.yaml`, so out of scope by the contract.
- **One assertion dropped from `Corner/endpoints/corner_payment_amount_must_equal_invoice_total`**: the recipe expects `ERR_INVOICE_NOT_VOIDABLE` when voiding a `PAID` invoice, but PRD §2.8 band 5 says a terminal current state returns the terminal code and stands the transition check down (`ERR_EMPLOYERINVOICE_TERMINAL`), while §3.9 names `ERR_INVOICE_NOT_VOIDABLE` — the PRD does not uniquely derive the outcome, so that step is omitted. The rest of the instance (exact-total payment, under/overpayment refusals, ytd and reservation `billing_status` roll-forward) is tested.

## Recipe defects found and repaired PRD-first

1. `corner_incident_report_open_to_under_review_transition` uses `category: "SAFETY"`, outside the PRD's five-member enum — tested with `SUPERVISION`.
2. `incident_fork_substantiate_probation_versus_dismiss_no_op` asserts `last_status_reason_code == RATIO_BREACH_CONFIRMED`; PRD line 179 requires `INCIDENT_SUBSTANTIATED` for an incident-driven `CREDENTIALED → PROBATION` — the PRD value is asserted.
3. `employer_money_ledger_survives_invoice_issue_and_void` confirms R2 before completing R1; per §3.6 stage three step two R2's outstanding `RESERVE` would drive R1's `covered_days` to 0, contradicting the recipe's own figures — the world completes R1 first, which reproduces every asserted number.
4. Earlier repairs still in force: an unreachable `OFFERED` row in the maintenance-sweep world (fixed by adding a 2026-08-30 block), recipe HTTP statuses corrected to §5 values (`ERR_BLOCK_DATE_MISMATCH` 400, `ERR_INVALID_ACTUAL_WINDOW` 400), and a non-PRD check-in stamping assertion dropped.
5. Stage-1 bug found and fixed: `payment_payload` used `amount_cents`; §3.9 and the endpoint input list say `paid_amount_cents`.

`workspace/implementation/` was never read, and no sibling task directory was accessed.

## Step 6: Generate implementation — 2026-09-01T18:09:53.998Z

The implementation is complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2287_employer_sponsored_backup_child_care/workspace/implementation/`:

- `start.sh` (launcher, installs Flask only if missing, `exec python3 app.py`), `requirements.txt`
- `app.py` — blueprint registration under `/backup-care`, `ApiError` → envelope handler, 400/404/405/500 envelope handlers, `PORT` env (default 10000)
- Core: `db.py` (in-memory `Store`, 13 dicts, logical clock cold-start `2026-08-01T00:00:00Z`), `errors.py` (all 71 codes + statuses), `util.py` (Decimal/ROUND_HALF_UP helpers, datetime rendering, band-1 schema validators), `response.py` (meta envelope, pagination), `middleware.py` (auth, employee/provider scope)
- `services/`: `core.py` (row lifecycle, derived counters, 13 serializers, constants), `calc.py` (12 calculations), `matching.py` (candidate filter, ranking, offer batch), `cascade.py` (provider posture, withdrawal cascade, 6-step maintenance sweep), `invoice.py` (per-line rounding, sweep/issue/pay/void)
- `routes/`: `_common.py`, `ops.py`, `employers.py`, `plans.py`, `employees.py`, `providers.py`, `reservations.py`, `invoices.py`, `incidents.py`

## Endpoint count

**65** API endpoints registered (verified by walking `app.url_map`), matching the SCAFFOLD §1.5 table exactly. Storage is purely in-memory dicts; nothing is seeded at boot.

## Verification performed

Three smoke suites over the real app (0 failures): full happy path (employer → plan → activate → employee → dependent → provider → 4 credentials → credential review → capacity block → reservation → match → confirm → check-in → complete → invoice sweep → issue → payment → utilization report → incident → substantiate → maintenance), plus centre-based overage/`ERR_OVERAGE_NOT_PERMITTED`, late cancel penalty, invoice void returning reservations to `ACCRUED`, no-show strikes, reject-offer/exclusion cycle, block overlap vs. touching boundary, OCC 412 on both guards, scope 403s, provider immutability, credential revoke → suspension → withdrawal cascade → reinstatement gates. Arithmetic spot-checks hold (4.25 h × 605 ¢ = 2571 with per-line rounding; admin fee 2571 × 0.085 rounds half-up). Also booted via `bash start.sh` on a live port and confirmed the envelope over real HTTP.

## Notes / judgement calls

1. **14-hour window ambiguity**: PRD §2.8 band 1 attaches the >14 h rule to `ERR_INVALID_WINDOW` (priority 115), while PRD §3.4 and SCAFFOLD §1.6 attribute it to `ERR_CARE_WINDOW_SPANS_DAYS` (priority 505). I emit `ERR_CARE_WINDOW_SPANS_DAYS` right after the same-date check (both are HTTP 400).
2. Two declared checks are unreachable and were skipped: the invoice-issue "no billed reservation still `IN_SERVICE`" precondition, and `ERR_PLAN_EMPLOYER_MISMATCH` on `POST /benefit-plans`. `POST /providers` defines no uniqueness rule, so no `ERR_DUPLICATE_KEY` there.
3. Derived fields (counters, scores, occupancy, `block_status`, `enrolled_employee_count`) are computed on read and never bump `version`; `CapacityBlock.version` is bumped only at confirm / cancel-from-CONFIRMED / complete / no-show / provider withdrawal.
4. Maintenance step 4 expires *every* offer past its TTL (literal PRD wording), including the `SELECTED` offer of an already-confirmed reservation.
5. Reservations carry four hidden non-serialized fields (`_covered_qty`, `_overage_qty`, `_copay_unit`, `_overage_unit`) written by confirm/complete and read verbatim by invoice line generation, per PRD §3.6 stage four.

## Step 7: Run tests and iterate — 2026-09-01T22:00:44.410Z

## Summary

### Iterations run
- **Iteration 1** (pre-fix): 8-round parallel sweep → 8 genuine failures (identical in all 8 rounds) + a floating set of harness-only `error` outcomes.
- **Iteration 2** (post-fix): three *completed* 8-round parallel sweeps (24 rounds, 2352 test executions). Two further sweeps were killed mid-run by an external process on the shared host and are not counted.
  - **`failed` count across all 24 completed rounds: 0. Assertion failures: 0.** Every one of the 98 tests passed in multiple rounds; all 8 originally-failing tests pass.
  - The only non-passes are `error` outcomes, **100% of them (916/916) the same host artifact**: the runner's own per-test server-restart step (`pids=$(lsof -ti:PORT -sTCP:LISTEN); kill -9 $pids`) exceeding its internal 5 s `subprocess` timeout. The box was running 230–400 concurrent `prd-bench-local-run` processes from other agents at load averages of 250–2151; the affected test set is different every round and every failure is in *setup*, before any HTTP request. This is not reachable from `test_suite/`, `test_helpers/` or `implementation/`, so a literal 8/8-green sweep is not obtainable in the current host window.

### Tests deleted
None. One **assertion** was removed under STEP 1c partial coverage:
- `test_04_reservation_intake_and_state_guards.py::test_cancelling_twice_reports_terminal_and_preserves_the_first_cancel` — dropped `assert after["cancelled_at"] == cancelled["cancelled_at"]`. **PRD-SILENT (field never named)**: `cancelled_at` appears nowhere in PRD.md. Scaffold rule that drove generation: `Corner/state_machines` terminal-cancel idempotence. The surrounding covered assertions (`cancel_reason_code`, unchanged `version`, `ERR_RESERVATION_TERMINAL`) were kept.

### Fixes applied to `test_suite/`
- `test_01_employer_and_benefit_plan_administration.py`, `test_employer_plan_and_invoice_guards_each_return_their_own_code` — inline payment payload `{"amount_cents": 0}` → `{"paid_amount_cents": 0}`; PRD §3.9 names `paid_amount_cents`, so the old key was a band-1 shape violation and the implementation's `ERR_INVALID_REQUEST` was PRD-correct.
- `test_04...py`, `test_every_freshly_created_row_lands_on_its_declared_initial_state` — `invoice["status"]` → `invoice["invoice_status"]`; PRD §3.9: "The sweep creates the invoice with `invoice_status` `DRAFT`".
- `test_04...py`, `test_a_request_with_no_user_id_header_never_leaks_a_later_band` — the anonymous call sent `{"industry_code": "MIXED"}`, omitting the required `name`. PRD §2.8 orders band 1 (Request shape) *ahead* of band 2 (Auth), so `ERR_INVALID_REQUEST` was PRD-faithful and the test's own docstring claim ("Band 2 runs ahead of … request shape") contradicted PRD. Payload replaced with a shape-valid `employer_payload(...)` so the missing header is the only defect; docstring corrected.
- `test_04...py`, `test_no_role_dominates_another_so_each_peer_operation_is_refused` — provider now created with `same_day_available=True`. PRD §3.3 declares that field "defaulting to false", so the post-denial `assert unchanged["same_day_available"] is True` was unsatisfiable and the refused `PATCH ... {"same_day_available": False}` had nothing to undo.
- `test_10_provider_withdrawal_and_maintenance.py`, `TestNightlyMaintenanceSweep._sweep_world` — two setup repairs (fixed both sweep tests):
  1. The world expected the provider whose `LICENSE` expires 2026-08-15 to be offerable for care on 2026-08-30, which PRD §3.5's candidate filter forbids ("`expires_on` is on or after the reservation's `care_date`"). Added a second, fully-credentialed `MKT-CMH` provider that owns the 2026-08-30 block and publishes the surviving offer.
  2. Matching that reservation is now done at clock `2026-08-15` instead of `2026-08-01`, because PRD §3.5 sets `offer_expires_at` to clock + 48 h capped at `care_start_utc` — otherwise the offer would be past TTL and step four would count 2, not 1.

No `test_helpers/` change was needed (`payment_payload` already used the correct key; the two defective payloads were inline in the test files).

### Fixes applied to `implementation/`
- `workspace/implementation/routes/incidents.py`, `substantiate_incident` — when the `qa_action` target is `PROBATION`, `set_provider_status` is now handed `INCIDENT_SUBSTANTIATED` rather than the caller's `resolution_reason_code`. PRD §3.3: "`CREDENTIALED → PROBATION` … records `last_status_reason_code` from the supplied reason code (or from `INCIDENT_SUBSTANTIATED` when it is driven by a substantiated incident)". `SUSPENSION`/`DEPROVISION` targets still record the supplied code, since PRD names no substitute value for them.

No endpoint, field, side effect or capability was added; storage remains in-memory dicts with nothing seeded at boot; no assertion was weakened and no skip/xfail was introduced.

### Orchestrator verification note

Final orchestrator evidence (2026-09-01T23:31Z), collected after Steps 8–9: **16 further per-test-server rounds** (the canonical 8-round parallel sweep preserved in `workspace/implementation/results.{1..8}.json`, plus 8 additional rounds run only for union coverage and then deleted) = **1568 test executions with 0 assertion failures (`failed: 0` in every round)**. 97 of the 98 tests passed in at least one of those rounds; the single test that never got a slot — `test_no_role_dominates_another_so_each_peer_operation_is_refused` — was then run on its own against a server freshly booted from `start.sh` and **passed** (`1 passed, 97 deselected`). So all 98 tests are confirmed passing against a fresh-boot server, with zero assertion failures observed anywhere.

Of the 1568 executions, 1111 ended in the harness `error` outcome: 1109 are the runner's own per-test restart step (`lsof -ti:PORT -sTCP:LISTEN; kill -9`) exceeding its internal 5 s `subprocess` limit, and 2 are a boot-time connection reset. All occur in *setup*, before any HTTP request reaches the implementation, and the affected test set is different in every round.

The orchestrator independently re-ran the suite (4 rounds at reduced concurrency, then a sequential retrying 8-round sweep) and confirms the subagent's diagnosis: **0 assertion failures**; every non-pass is host infrastructure — the runner's own `lsof`-based server-restart step timing out at its internal 5 s limit, or a `ConnectionResetError` during boot, both while the 32-core host carried load averages of 300–412 with ~425 concurrent `prd-bench-local-run` processes belonging to other pipelines. No non-pass reaches an HTTP request against the implementation.

## Step 8: Finalize PRD — 2026-09-01T22:12:12.942Z

PRD_FINALIZED.md is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2287_employer_sponsored_backup_child_care/workspace/PRD_FINALIZED.md`.

## Metrics

- `PRD.md`: 420 lines → `PRD_FINALIZED.md`: 420 lines (**0.0%** line delta)
- 9 lines revised in place (`1 file changed, 9 insertions(+), 9 deletions(-)`)
- Characters: 98,932 → 101,059 (**+2,127, +2.15%**)
- No new sections, no headings added, no reordering; every untouched line is byte-identical.

## One bullet per change

- **§2.5 (Common resource fields)** — revise — `version`/`updated_at` now bump only on writes of a *stored* field; the derived-on-read figures are enumerated (employee entitlement counters + `eligibility_status`, plan `enrolled_employee_count`, provider's two score variants + substantiated-incident/completed-reservation counts, employer accrual + YTD billing, capacity-block occupancy) and "recomputes" is defined as a statement about the next read, not a mutation — `implementation/services/core.py:66-68` (sole `touch()`), `:149`, `:182`, `:201`, `:211`, `:221`, `:269`
- **§2.8 band 1** — revise — the 14-hour ceiling is removed from the band-1 `ERR_INVALID_WINDOW` check and explicitly redirected to band 6; the strict-ordering check for reservations and capacity blocks stays in band 1 — `implementation/routes/reservations.py:164`, `:184-185`
- **§2.8 band 6** — revise — the >14h window is checked immediately after the same-UTC-date check and reports `ERR_CARE_WINDOW_SPANS_DAYS` (400), not `ERR_INVALID_WINDOW` — `implementation/routes/reservations.py:80`, `:183-185`
- **§2.8 band 7** — revise — `ERR_PLAN_EMPLOYER_MISMATCH` fires on employee creation and on the employee amendment that moves a person onto another plan, and never on benefit-plan creation — `implementation/routes/employees.py:73`, `:143`
- **§2.8 uniqueness-keys paragraph** — revise — `name` is checked on employer creation and `employee_external_id`/`user_id` on employee creation; provider creation enforces no uniqueness key and never returns `ERR_DUPLICATE_KEY` (providers may share `provider_name`, `market_code`, `owner_user_id`) — `implementation/routes/providers.py:60-95` (no check), `:183`; `implementation/routes/employees.py:77`, `:82`
- **§3.1 (Benefit plan drafting)** — revise — the plan/employer guard is enforced at enrolment or plan move, not at drafting time — `implementation/routes/plans.py:64-133`; `implementation/routes/employees.py:73`, `:143`
- **§3.3 (Provider posture)** — revise — `CREDENTIALED → PROBATION` records the supplied reason code only when a `network_admin` names `PROBATION` as `target_status`; when incident-driven it records the fixed `INCIDENT_SUBSTANTIATED`, never the report's `resolution_reason_code` — `implementation/routes/incidents.py:148-155`; `implementation/routes/providers.py:291`
- **§3.8 (Substantiation)** — insert (one sentence) — reason code by action: `PROBATION` stamps `INCIDENT_SUBSTANTIATED`; `SUSPENSION`/`DEPROVISION` stamp the supplied `resolution_reason_code` — `implementation/routes/incidents.py:152-155`
- **§3.9 (Maintenance sweep, step four)** — revise — step four expires every offer still `PROPOSED`/`SELECTED` past TTL, reading the offer alone and never its reservation's state, so a `SELECTED` offer of an already-confirmed reservation is expired like any other; `REJECTED`/`EXPIRED` offers untouched — `implementation/services/cascade.py:152-160`

## Per-edit pre-edit search log

1. **§2.5 — subject: what bumps `version`/`updated_at`.** Enumerated `services/core.py:66` `touch()` as the only writer, then grepped all 40 `touch(` callsites (`employers.py:145`; `cascade.py:59,61,69,84,101,122,149,159,168`; `incidents.py:115,146,178`; `reservations.py:360,368,451,462,500,520,522,551,589,619`; `matching.py:164,192,227`; `providers.py:153,233,267`; `invoice.py:150,158,164,169,187,193`; `employees.py:149,275`; `plans.py:198,237,241`) and read every serializer computing counters (`core.py:149,182,201,211,221,235,269`). **Adjustment:** excluded `block_status` from the derived list because maintenance step 5 writes a stored `closed` flag (a real mutation), and appended "Exactly one row is nevertheless re-stamped for a purely occupancy-driven reason" so §2.5's pre-existing capacity-block paragraph below stays true (`reservations.py:462,520,619`, `cascade.py:61,101`).
2. **§2.8 band 1 — subject: which window failures are band 1.** Read `routes/reservations.py:80,160-190` and `routes/providers.py:307-308` (block `ERR_INVALID_WINDOW`) plus `errors.py` status map. **Adjustment:** kept `ERR_INVALID_WINDOW` in band 1 covering *both* the reservation and capacity-block strict-ordering checks so the block path remains described; only the 14-hour clause moved out.
3. **§2.8 band 6 — subject: code and position of the 14-hour ceiling.** Same paths; confirmed evaluation order 164 → 178 → 181 → 183 → 185 and that §3.4 already said SPANS_DAYS "also covers a window longer than 14 hours" (left verbatim, no contradiction introduced).
4. **§2.8 band 7 — subject: `ERR_PLAN_EMPLOYER_MISMATCH` raise sites.** Grepped the code across the tree: only `routes/employees.py:73` (create) and `:143` (PATCH plan move); read `routes/plans.py` create/patch/activate and found none. **Adjustment:** initial wording said "employee creation" only; widened to include the plan-moving amendment after finding line 143 (NO-NEW-MISMATCH).
5. **§2.8 uniqueness keys — subject: `ERR_DUPLICATE_KEY` raise sites.** Grepped all five: `employers.py:84`, `employees.py:77,82`, `plans.py`, `providers.py:183` (credential type); read `create_provider` (`providers.py:60-95`) in full. **Adjustment:** added the explicit "two providers may freely share a `provider_name`, a `market_code` or an `owner_user_id`" only after confirming no such check exists anywhere, including PATCH.
6. **§3.1 — subject: same linkage guard from the plan side.** Re-used the band-7 enumeration; verified plan creation validates only employer existence and plan-code uniqueness. **Adjustment:** phrased as "enforced when an employee is enrolled against the plan or later moved onto it" to match both raise sites rather than naming a single endpoint.
7. **§3.3 — subject: every writer of `last_status_reason_code`.** Read `services/cascade.py:66-72` (`set_provider_status`) and all its callers: `routes/providers.py:241` (`CREDENTIAL_REVOKED`), `:266` (`reason_code or "CREDENTIAL_REVIEW_PASSED"`), `:291` (caller-supplied), `services/cascade.py:122,132` (sweep `CREDENTIAL_EXPIRED`), `routes/incidents.py:155`. **Adjustment:** scoped the sentence to the direct-`target_status` and incident-driven paths so the PRD stays *silent* (not wrong) about the revoke/review/sweep constants, which no step_7_diff item touches.
8. **§3.8 — subject: substantiation-driven reason code per `qa_action`.** Read `routes/incidents.py:136-155` and `QA_TARGET` (`:28-32`), plus `test_suite/test_11...py:244` (asserts `INCIDENT_SUBSTANTIATED`) and `test_suite/test_03...py:296-318` (SUSPENSION path leaves the code unasserted — tests are laxer than impl, so impl was the target). **Adjustment:** covered all three non-`NONE` actions in one sentence rather than only PROBATION, and left `NONE` described as touching nothing.
9. **§3.9 step four — subject: which offers step four sees.** Read `services/cascade.py:152-160`, `services/matching.py:156-164` (`expire_offers`) with all five callers, `matching.py:231-235` (`selected_offer`), `routes/reservations.py:395-397` (confirm leaves the offer `SELECTED`); cross-checked `test_suite/test_10...py:164-319` where `offers_expired == 1` comes from the SELECTED offer of the confirmed reservation. **Adjustment:** added "reads the offer alone and never the state of the reservation that owns it" so the wording also covers cancelled-from-CONFIRMED and rematch-orphaned `SELECTED` offers, instead of a narrow claim about confirmed reservations only.

## step_7_diff items deliberately left unpatched

- **Deleted `cancelled_at` assertion** — the field exists in neither `implementation/` nor PRD (`s_reservation`, `core.py:471`, does not emit it); adding prose would invent behavior.
- **Five `test_suite` fixture fixes** (`paid_amount_cents` key, `invoice_status` key, shape-valid anonymous payload, `same_day_available=True`, test_10 `_sweep_world`) — all were test-side bugs against behavior PRD already determines uniquely; no PRD silence.
- **Four hidden non-serialized reservation fields** (`_covered_qty`, `_overage_qty`, `_copay_unit`, `_overage_unit`, `reservations.py:120-130`) — private storage of quantities PRD §3.6 stage four and §3.9 already pin; naming them would over-determine an internal representation.
- **Unreachable invoice-issue `IN_SERVICE` / other unreachable checks** — no error code is reachable and no observable behavior differs, so any wording would be a false universal claim.

Per the "prefer under-determined wording" rule I also noted but did not edit: `dependent_ids` validated before the window check, the void-from-`PAID` code choice, multiple simultaneous `SELECTED` offers after rematch, `offers_expired` step attribution, and the `CREDENTIAL_REVOKED`/`CREDENTIAL_EXPIRED` reason-code constants — PRD-silent, but none traces to a `<step_7_diff>` item.

## Step 9: Complete PRD — 2026-09-01T22:26:50.796Z

Done. All planned edits are applied to `/home/ubuntu/github/CodingPRD/tasks/task_2287_employer_sponsored_backup_child_care/workspace/PRD_COMPLETED.md`.

## File comparison

| File | Lines | Chars |
| --- | --- | --- |
| `workspace/PRD_FINALIZED.md` | 420 | 101663 |
| `workspace/PRD_COMPLETED.md` | 423 | 108050 |

Char delta: **+6387** (+3 lines: 2 new error-catalogue table rows, 1 new bullet in the §2.2 error-format bullet list). 26 diff hunks total; no section added, no section removed, no reordering.

## Counts

- **ambiguity-pins: 29**
- **mismatch-revisions: 7**

## Changes

- §2.1 — revise — ambiguity — `ERR_UNAUTHENTICATED` covers a blank/absent `X-User-ID` *and* a blank/absent/unrecognised `X-User-Role`, both before any role authorisation — `middleware.py:25-30`
- §2.2 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404, wrong method on a routed path → `ERR_METHOD_NOT_ALLOWED` 405; entity `..._NOT_FOUND` codes reserved for routed-but-unresolved ids — `app.py:42-50`
- §2.3 — revise — ambiguity — each of the three overriding orderings breaks ties by `created_at` ascending; ledger replay is `effective_at` then created-order — `routes/employers.py:156,181`, `services/core.py:117`
- §2.3 — revise — **mismatch** — offer listings sort by `rank_position` ascending across the whole filtered set, not "within a generation batch" — `routes/reservations.py:697`
- §2.5 — revise — **mismatch** — PRD claimed three fractional digits on stored instants; impl omits the fractional part when zero, and the whole-second clock makes it always zero, so stored instants render `...T00:00:00Z` and only `api_request_timestamp` carries three digits — `util.py:fmt_dt`, `util.py:parse_dt_value`
- §2.8 band 1 — revise — **mismatch** — `dependent_ids` shape validation runs *before* the `ERR_INVALID_WINDOW` care-window check on reservation creation — `routes/reservations.py:163-165`
- §2.8 band 1 — insert — ambiguity — reason-code style fields are non-empty strings of at most 80 characters — `routes/reservations.py:340,473,626`, `routes/invoices.py:78`, `routes/incidents.py:123,163`
- §2.8 band 2 — revise — **mismatch** — twelve surfaces (not "exactly seven") apply the `employee_user` ownership scope check — `middleware.py:49`, `routes/employees.py:105,159,169,192,215,232,251,265`, `routes/reservations.py:168,273,344,477`
- §2.8 band 2 — revise — **mismatch** — eight surfaces (not "exactly five") apply the `provider_manager` ownership scope check — `middleware.py:58`, `routes/providers.py:175,204,217,312,351`, `routes/reservations.py:532,565,630`
- §2.8 band 3 — insert — ambiguity — an employee amendment that names a `benefit_plan_id` resolves and re-links it under the existence band — `routes/employees.py:124-152`
- §3.1 — insert — ambiguity — `plan_code` is a non-empty string of at most 80 characters — `routes/plans.py:69`
- §3.1 — insert — ambiguity — `effective_from`/`effective_to` are parsed and compared as full instants, not calendar dates — `routes/plans.py:84-86,218,233`
- §3.1 — insert — ambiguity — editing a `SUPERSEDED` plan returns `ERR_PLAN_NOT_EDITABLE`, and an omitted/null field on amendment leaves the stored value unchanged — `routes/plans.py:180`
- §3.1 — insert — ambiguity — plan listings filter on `employer_id`, `status` and `superseded_by_plan_id` — `routes/plans.py:146-148`
- §3.2 — insert — ambiguity — `employee_external_id` ≤80 chars, `email` ≤200 chars and must contain `@` — `routes/employees.py:53-56`
- §3.2 — insert — ambiguity — employee listings filter on `employer_id`, `benefit_plan_id`, `employment_status`, `eligibility_status` — `routes/employees.py:112-115`
- §3.2 — insert — ambiguity — the entitlement projection's `days_limit` carries two decimals; ledger listings filter on `entry_type` and `benefit_year_start` — `services/calc.py:230`, `routes/employees.py:233-234`
- §3.2 — insert — ambiguity — dependent `date_of_birth` is mandatory, `care_notes` is optional, ≤2000 chars, and defaults to the empty string — `routes/employees.py:183-187,201`
- §3.3 — insert — ambiguity — provider listings filter on `market_code`, `care_mode`, `network_status`, `same_day_available` — `routes/providers.py:108-111`
- §3.3 — insert — ambiguity — `issued_on` and `expires_on` are both mandatory and a missing one is `ERR_INVALID_REQUEST`, with `expires_on` strictly after `issued_on` — `routes/providers.py:165-169`
- §3.3 — insert — ambiguity — a revocation that strips a required type suspends the provider with `last_status_reason_code` `CREDENTIAL_REVOKED` — `routes/providers.py:241`
- §3.3 — insert — ambiguity — the full network-status reachability table, including `PENDING` accepting no direct posture move and `SUSPENDED → CREDENTIALED`/`DEPROVISIONED` only — `services/cascade.py:17-23`
- §3.3 — insert — ambiguity — the block-overlap test considers only that provider's same-`service_date` blocks whose derived status is not `CLOSED` — `routes/providers.py:324-329`
- §3.5 — insert — ambiguity — every match run, publishing or not, re-stamps `updated_at` and bumps `version`, and clears `unfulfilled_reason_code` whenever it publishes — `services/matching.py:173,192,227`
- §3.5 — insert — ambiguity — the reject-offer trio is ordered `ERR_OFFER_EXPIRED`, then `ERR_OFFER_RESERVATION_MISMATCH`, then `ERR_OFFER_NOT_SELECTED`, all after the `OFFERED` state check — `routes/reservations.py:351-356`
- §3.6 — revise — ambiguity — a block whose `service_date` differs from the reservation's `care_date` reports `ERR_WINDOW_OUTSIDE_BLOCK` via the containment check rather than a dedicated code — `routes/reservations.py:418-421`
- §3.6 — insert — ambiguity — `confirmation_code` is `CONF-` plus exactly eight uppercase-alphanumeric characters — `routes/reservations.py:84-85`
- §3.7 — insert — ambiguity — the no-show `reason_code` is optional, validated non-empty and ≤80 chars, but is stored on no field and invisible in the response — `routes/reservations.py:626,638`, `services/cascade.py:75-101`
- §3.8 — insert — ambiguity — both `qa_action` and `resolution_reason_code` are mandatory on substantiation, the reason code ≤80 chars — `routes/incidents.py:122-123`
- §3.8 — revise — **mismatch** — `DEPROVISION` is accepted from `SUSPENDED` as well as `CREDENTIALED`/`PROBATION` — `services/cascade.py:17-23`, `routes/incidents.py:136-141`
- §3.8 — insert — ambiguity — the posture check precedes every write, so an `ERR_PROVIDER_STATE_INVALID` refusal leaves the report `UNDER_REVIEW` with `qa_action`, `resolution_reason_code`, `updated_at` and `version` untouched — `routes/incidents.py:135-146`
- §3.9 — insert — ambiguity — every reservation in the billable set moves `ACCRUED → INVOICED`, including one whose candidate lines all rounded to zero and were never written — `services/invoice.py:46-63,149`
- §3.9 — revise — **mismatch** — deleted the claim that issuance requires no billed reservation still be `IN_SERVICE`; issuance tests only `line_count` and `total_cents` — `routes/invoices.py:45-50`
- §3.9 — insert — ambiguity — voiding an already-`VOID` invoice returns `ERR_EMPLOYERINVOICE_TERMINAL` while a `PAID` one returns `ERR_INVOICE_NOT_VOIDABLE` — `routes/invoices.py:83-86`
- §3.9 sweep step two — insert — ambiguity — the sweep-driven suspension records `last_status_reason_code` as the fixed string `CREDENTIAL_EXPIRED` — `services/cascade.py:131-133`
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` 404 and `ERR_METHOD_NOT_ALLOWED` 405 rows — `app.py:42-50`

Deliberately not changed (minimality): the `has_more` formula, tolerance of unknown query parameters, and the `ERR_INTERNAL` 500 catch-all, which is a defensive handler no specified behaviour reaches.
