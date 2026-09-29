# Worklog — task_2627_home_improvement_point_of_sale_financing

## Step 1: Create task directory — 2026-09-03T21:26:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2627_home_improvement_point_of_sale_financing` and `workspace/` (pre-assigned path; no index scan performed per orchestrator instruction).

## Step 2: Generate scaffold — 2026-09-03T23:42:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2627_home_improvement_point_of_sale_financing/`
- `SCAFFOLD.yaml` — 2379 lines. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3249 lines, single top-level key, **24 depth instances**.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6690 lines, single top-level key, **81 breadth instances (63 real + 18 `excluded_because` stubs)**.

`workspace/` and `worklog.md` untouched.

## SCAFFOLD.yaml rule counts
14 entities · 10 state machines · 3 `concurrency_rules` · 10 calculations · 54 ordered validations · 53 endpoints (31 POST / 22 GET) · 68 errors · 6 roles.

## §1.9 section coverage (all 9 sections)
entities 12 · state_machines 17 · calculations 14 · validations 9 · endpoints 6 · errors 9 · rbac 5 · cross_cutting_complexity_layers 8 · consistency_model 1.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1696

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks: no duplicate instance names across §1.8+§1.9; every stub cites a real §1.8 instance and carries no `test_recipe`; every `${var}` is bound by an earlier `captures:`; every `expected_*_version` payload value contains a `${var}`; all 68 error ids are referenced by at least one instance; the only call intentionally lacking `as_user_id` is the 401 `ERR_UNAUTHENTICATED` probe.

## Design adjudications
- **Domain economics**: instant decision keyed on FICO floor 620 + four limit tiers + a DTI ceiling of 4500 bps evaluated *before* ticket comparison (so a DTI failure is never counter-offered); settlement discount is a genuine dual-variant calculation (PROVISIONAL = plan rate + trade holdback, speed ignored; FINAL = component-wise negotiated rate + speed surcharge − credit, with the reserve gap applied).
- **Threshold placement**: the reserve-suspension floor was engineered to be crossed by one cent — a 48005 claim leaves `reserve_coverage_bps` at exactly 5000 (4999.58 rounds up) and the merchant stays APPROVED; one more cent of claim yields 4999 and trips `RESERVE_COVERAGE` suspension. Kills round-down and `<= 5000` implementations.
- **Priority-collision routing**: several error instances had to be reached indirectly because an earlier-priority validation shadows them — `ERR_DISPUTE_NOT_REOPENABLE` via a day-31 clock rather than a live case, `ERR_LOAN_CLOSED` asserted instead of `ERR_PAYMENT_EXCEEDS_PAYOFF`, and `ERR_LICENSE_EXPIRED` reached only after widening the enrollment window so the shared priority-31 alternation falls through to the licence clause.
- **`ERR_DTI_LIMIT_EXCEEDED` gap**: a 68-id coverage diff showed the §1.8 DTI instance probes application-time DECLINE (no error id), so a dedicated §1.9 errors instance was added for the acceptance-time recomputation breach (`dti 4740 → REVOKED`) rather than an `excluded_because` stub.
- **OCC**: one instance per §1.2.1 rule, each staling the version through a *different* route — a replayed identical holdback DEPOSIT, a settlement that bumps `LoanAccount.version` between two draw creations, and a second settlement that bumps `Merchant.version` under a pending dispute resolution. The replay design is version-bump-agnostic (capture → succeed → replay → 412 → re-capture → succeed).
- **Segregation of duties respected in fixtures**: sa-1 releases draws, so every dispute resolution in those instances is taken by sa-2 (priority-11 SoD fires before the 412 band).
- **Layers deliberately not emitted**: `soft_delete`, `idempotency`, `multi_tenancy`, `bulk_operations`, `conditional_feature_flags` (not declared in `complexity_layers`) and `pagination_with_filtering` (already covered by the entities pagination instance). `cascading_side_effects`, `dual_variant_calculation` and `derived_field_reconciliation` are stubs pointing at their deeper §1.8 counterparts.
- **Endpoint adjudications during final wiring**: there is no `/merchants/{id}/portfolio-performance` route — portfolio metrics are read through `GET /merchants/{id}` and, in the consistency instance, through the filtered `GET /merchants?risk_tier=STANDARD` collection read; the sweep is `POST /servicing/expiration-sweeps` and the clock field is `current_utc`.
- **Response envelope**: all error asserts use `data.error_id` / `data.message` (an earlier pass that used `error.code` was globally corrected).

## Step 3: Copy shared files — 2026-09-03T23:43:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T00:03:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **497 lines**, written in 11 incremental heredoc appends (`cat >` then 10 × `cat >>`), each verified with `wc -l` + `tail`. File ends at a real boundary: the last row of the §5 error table. No audit footer, no Hard Contract report inside the document.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed block) · 2.3 Pagination · 2.4 Monetary Units, Rate Units and Rounding · 2.5 The Logical Clock and Interval Conventions · 2.6 Common Resource Properties and Record Versioning · 2.7 Left-to-Right Path Resolution · 2.8 Optimistic Concurrency on Merchant and Loan Account Versions · 2.9 The Order in Which a Request Is Judged · 2.10 Cascade Integrity and Derived-Figure Recomputation
- §3 Business Logic & Workflows — 3.1 Program Reference Data · 3.2 Merchant Onboarding · 3.3 Promotion Enrollment · 3.4 At the Kitchen Table: Consumer Registration and the Instant Decision · 3.5 Disclosure, Acknowledgement and Loan Origination · 3.6 The Project: Scope, Milestones and Completion Certification · 3.7 Staged Funding: Release Headroom and the Draw Request · 3.8 Settlement Economics, the Holdback Reserve and Reversal · 3.9 Deferred-Interest Servicing: Accrual, Payments and the Expiration Sweep · 3.10 Disputes, Chargebacks and the Four-Hop Cascade · 3.11 Phantom Projects, Portfolio Grades and Program Termination
- §4 API Endpoint Definitions (4-column table: Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue (2-column table: Error ID, HTTP Status Code)

**Coverage confirmation (mechanically checked against the scaffold, not asserted)**
- Entities: 14/14; all 145 entity field names present verbatim in backticks. `Payment`'s `common_fields: false` exception documented in §2.6.
- State machines: 10/10; all 43 distinct state values present; all transitions narrated, including the parallel dimensions (`CreditApplication` decision × disclosure, `LoanAccount` promo × balance), the cyclic ones, and both branching pairs with symmetric side-effect treatment (SETTLE/DENY, MERCHANT_FAVOR/CONSUMER_FAVOR, CONFIRMED/CLEARED).
- Concurrency rules: 3/3 in §2.8, each with write endpoint, OCC field, error ID and HTTP 412, plus "endpoints not named take no version field".
- Calculations: 10/10, with pinned evaluation orders reproduced in prose (6-step instant decision, exact-sum-then-round-once accrual, three-independent-roundings FINAL draw variant, pinned six-step reserve target with its three order-sensitivity traps, staged-funding headroom, strict-`>` velocity cap, three-bucket chargeback waterfall with conservation, payment waterfall with the overpayment gate first, grade table A→B→C→D with MIN_SEASONED_DRAWS 5, halve-the-aggregate-once fraud score with the exact cross-multiplied SYSTEM detector).
- Validations: 54/54 as a numbered priority list in §2.9. Diffed error-ID-by-error-ID against scaffold priorities 1–54: exact order match, including the four dual-error entries (16, 17, 31, 34) which carry both codes, and the multi-code existence entries (5, 6) which delegate to §2.7.
- Endpoints: 53/53 rows in §4, roles copied per-endpoint from the scaffold `roles:` lists.
- Errors: 68/68 rows in §5 with matching HTTP status codes (generated directly from the scaffold to eliminate transcription drift).
- Roles: 6/6, all named in §2.1 with entity-backed vs opaque identity, scope violations and both segregation-of-duties checks.

**Hard Contracts**
- Contract 1 (Field-Name Coverage) PASS — 156 scaffold field/request/query/path-param names extracted; `comm` against the PRD's backticked-token set returned zero missing. All 10 sweep/clock response field names also present.
- Contract 2 (Rule Coverage) PASS — all six high-risk categories verified (priority ordering exact-diffed; all three OCC rules with error+status; cross-entity cascades stated with their causal chains, including the 4-hop chargeback and 3-hop fraud cascades; every validation's `applies_to` scope translated into a "guards…" clause; field-level structured content present; sibling branches given equal treatment).
- Contract 3 (§3 Path Purity) PASS — extracted every backticked token in lines 183–362 (all of §3): zero tokens start with `/`, zero are bare HTTP methods, zero are method+path, zero contain a slash at all.

Style checks also clean: no fuzzy quantifiers, no pseudocode operators, no placeholders. §2.2 is content-identical to `section-2.2-response-structure.md`. The two withheld files were never opened, grepped, or referenced; no scaffold `worked_example` numbers were copied into the prose — only the rules they illustrate.

**Orchestrator truncation check (per skill guard):** `tail -30` shows the file ending on the final `ERR_PAYMENT_EXCEEDS_PAYOFF | 422` table row — a real section boundary. Independent counts confirm 53 endpoint rows and 68 error rows. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T00:45:00.000Z

Generation complete. Final state, fully audited.

## Files written (all at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 2 005 lines
| file | lines | contents |
|---|---|---|
| `types.py` | 158 | every enumerated value once (6 roles, trade/promotion types, 12 status vocabularies, reason codes, sweep keys, common-field sets) |
| `api_errors.py` | 180 | all 69 `ERR_*` constants + `ERROR_HTTP_STATUS` + module-level `set_error_http_status_map(...)` so `validate_error` cross-checks status |
| `constants.py` | 264 | program constants (FICO tiers, DTI ceiling, volume-credit tiers, reserve-target rates, portfolio grades, window lengths) + the canonical scenario literals |
| `test_users.py` | 89 | 7 opaque operator handles + header builders; entity-backed `merchant_headers()` / `consumer_headers()` |
| `api_client.py` | 331 | `ApiClient(GenericApiClient)`, exactly **53 methods = 53 SCAFFOLD endpoints** (set-diff verified: missing `[]`, extra `[]`) |
| `assertions.py` | 219 | `round_half_up` / `bps_of` / `ratio_bps` primitives + domain assertions (common fields, event-only fields, component-wise discount, reserve coverage, chargeback conservation, reason codes) |
| `factories.py` | 250 | one payload builder per endpoint; passing `None` **removes** a field so tests can exercise omission |
| `fixtures.py` | 494 | `Scenario` bag + single-step helpers + layered builders `program → approved_merchant → enrolled_merchant → application → disclosed_application → activated_loan → project → project_with_milestones → settled_draw` |
| `__init__.py` | 20 | imports `api_errors` first so the status map registers on package import |

`test_suite/` — `conftest.py` (68 lines, **function-scoped** `api` because the harness restarts the server per test) plus 18 numbered files, 9 366 lines: `test_01` 244, `test_02` 284, `test_03` 358, `test_04` 427, `test_05` 298, `test_06` 484, `test_07` 436, `test_08` 378, `test_09` 497, `test_10` 681, `test_11` 1026, `test_12` 762, `test_13` 480, `test_14` 486, `test_15` 1166, `test_16` 599, `test_17` 572, `test_18` 120.

## Tests emitted

**287 test functions / 287 `Design:` lines** (292 collected items — one 6-way `parametrize` over the FICO band edges).

- **Queue A (difficulty): 24/24 instances covered, every one with ≥2 tagged tests** — 81 tests across `test_01`–`test_09`, one file per `rule_id`.
- **Queue B (corner): 63/63 live instances covered, every one with ≥1 tagged test** — 206 tests across `test_10`–`test_18`, one file per section.
- **All 18 `excluded_because:` stubs left untranslated**, and every stub's `difficulty_instance` cross-reference verified to resolve to a real queue-A instance name.

**Instances skipped: none.** No instance failed the PRD-first filter outright; where a recipe over-reached, the assertion was narrowed to what the PRD uniquely derives rather than dropped.

## Verification performed

`py_compile` clean on all 28 generated `.py` files; `pytest --collect-only` collects 292 tests with zero import errors; audit script reports zero dangling/dual/missing tags, zero stub tags, test-count == tag-count per file, and **zero non-verbatim PRD quotes** (every `PRD: "..."` is a byte-exact substring of `workspace/PRD.md`); no occurrences of "scaffold" or `§` in test text; `workspace/implementation/` never read or touched.

## Design adjudications (recipe narrowed, never weakened away)

1. **FICO 700 → 680** in `instant_decision_nested_min_over_tier_and_income_ceiling`: the recipe's 3 000 000 / 1 750 figures only follow from the 660–699 tier.
2. **Instant-valued timestamps asserted by prefix** (`offer_expires_at`, `disclosure_delivered_at`, `response_due_at`, `approved_on`, `verified_on`, `verified_at`): §2.6 pins three-fractional-digit rendering only for `created_at`/`updated_at`.
3. **Reconciliation delta** asserted as the arithmetic difference of two stored fields — the PRD names no field for it.
4. **`volume_tier_credit_bps` not asserted at draw creation**: the PRD says the five final-variant figures are *empty* there (the recipe said `0`).
5. **`max_fundable_now_cents == 0`**, not the recipe's 1 400 000, in the consistency instance: the release cap is the *lower* of verified share and completion cap.
6. **No `verified_by_user_id` on milestones** — the PRD stamps only `verified_at`.
7. **Post-reversal `first_funding_on` not asserted** (unpinned).
8. **Absolute merchant `version` literals replaced by a fresh read plus `+1`** wherever §2.6's "recomputation counts as a mutation" conflicts with the recipe; absolute versions kept where the PRD does derive them (LoanAccount 1→2→3, trade rule 1, merchant 2/3).
9. **`decision_dti_bps` rewrite on an acceptance-time revocation omitted** (unpinned).
10. **Dropped as not PRD-derivable:** the `?verification_status=` licence filter and the unrouted-method assertion. List corroborations use unfiltered counts against the per-test-empty DB rather than guessing query-parameter names.
11. **Flagged as an inference, not a citation:** `ERR_INVALID_MERCHANT_STATE` for REINSTATE-with-an-open-alert (derived from check 14 plus a closed error catalogue).
12. **Body-FK ordering fixture:** the recipe's placeholder id `...0000000000p1` is not valid hex and would trip priority-3 `ERR_INVALID_REQUEST` before reaching priority-6 FK resolution; substituted valid-hex non-existent UUIDs so the test actually observes declaration-order resolution.

One implementation-facing note worth passing on: the suite distinguishes the PRD's "*at zero*" wording (opening money figures on merchant/loan/project/dispute — asserted `== 0`) from its "*empty*" wording (line 277: the four draw stamps "and the five final-variant figures" on a `REQUESTED` draw — asserted absent/null). An implementation that renders the unsettled draw's `net_settlement_cents` as `0` instead of `null` will fail `test_12` and `test_11` on that rendering distinction, which the PRD does draw explicitly.

## Step 6: Generate implementation — 2026-09-04T01:05:00.000Z

Implementation complete for task 2627.

## Files written (`workspace/implementation/`, 3,666 lines of Python + launcher)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | `set -euo pipefail`, `cd "$(dirname "$0")"`, **guarded** `import flask` check, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 78 | blueprint registration, `ApiError` handler, 400/404/405/415/500 + catch-all handlers in envelope shape, `0.0.0.0:$PORT` (default 10000) |
| `util.py` | 93 | ISO-8601 3-digit instants, integer round-half-up, month arithmetic, `req_`-prefixed request ids |
| `errors.py` | 88 | ~70-entry error→HTTP status catalogue, `ApiError`, `fail()` |
| `response.py` | 43 | `meta`/`response_type`/`data` envelope, list `meta` with `limit`/`offset`/`total_count`/`has_more` |
| `store.py` | 68 | 14 in-memory dicts, logical clock at `2026-08-01T00:00:00Z`, `new_record`, `touch`, `(created_at,_seq)` ordering |
| `calc.py` | 531 | every pinned constant and derivation (instant decision, accrual, project aggregates, volume windows, final/provisional draw economics, six-step reserve target, chargeback waterfall, grades/tiers) |
| `validate.py` | 379 | auth, payload well-formedness, `_cents`/`_bps` non-negativity, pagination, path/body lookups, identity + scope |
| `serialize.py` | 288 | per-entity field sets; derive-on-read for every computed field; `Payment` without `updated_at`/`version` |
| `ops.py` | 259 | one-version-bump-per-record-per-request, suspend/reinstate/terminate cascades, phantom detector, capitalization, 7-family expiration sweep |
| `routes_program.py` | 645 | clock, sweep, trade rules, plans, merchants, licences, enrollment, program action, promotion enrollments, holdback adjustments, fraud alerts |
| `routes_credit.py` | 437 | consumers, POS applications, disclosure delivery/ack, acceptance + origination, loan accounts, payments |
| `routes_project.py` | 757 | projects, milestones, claim/verification, certification, funding draws, settlement, reversal, dispute cases, response, resolution |

**53 endpoints** implemented — exactly matching the PRD §4 table (verified by enumerating `app.url_map`). Storage is in-memory dicts only; nothing is seeded, preloaded or hardcoded at boot (verified: `GET /merchants` on a fresh process returns `total_count: 0`).

## Verification performed
- `python3 -m py_compile` clean on all 13 modules; `__pycache__` removed afterwards.
- Booted `PORT=18627 bash start.sh`, ran a 35-step end-to-end script: trade rule → plan → merchant → licence + verification → enrollment submission/approval → promotion enrollment → consumer → POS application (`decision_dti_bps` 1667, limit 5,000,000) → disclosure → ack → acceptance → loan account → project → milestone → claim → verification → draw → settlement → clock advance → accrual → payment → certification → dispute → merchant response → resolution → sweep ×2. Spot-checked figures all correct: settlement `effective_discount_bps` 400 (negotiated overrides plan), `merchant_discount_cents` 47,500 (40,000 base + 7,500 next-day − 0 tier credit), `holdback_withheld_cents` 40,000 (min of 100,000 base / 40,000 target gap / 150,000 per-draw cap), accrual 28,758 cents (1,000,000 × 2999 × 35 / 3,650,000 = 28,757.5, rounded half up), chargeback split 40,000 + 260,000 + 0 = 300,000 exactly, four-hop cascade fired (merchant `SUSPENDED` / `RESERVE_COVERAGE`, enrollment `SUSPENDED`, project `ABANDONED`), sweep idempotent (all zeros twice).
- Negative probes: 401 on missing/unknown role, 401 on write without `X-User-ID` but 200 on a read without it, 403 `ERR_ROLE_NOT_PERMITTED`, 403 `ERR_IDENTITY_UNKNOWN`, 409 `ERR_SEGREGATION_OF_DUTIES`, 409 `ERR_CONSUMER_SIGNOFF_REQUIRED`, 422 `ERR_CLOCK_NOT_MONOTONIC`, 400 on `limit=0`/`limit=101`/malformed JSON/negative `_cents`/instant without `Z`, 404 `ERR_DRAW_NOT_FOUND`, 405 envelope.
- Server killed **by captured PID** (`kill 3689042`, pid resolved from `ss` on port 18627 only); port confirmed free. No pattern kill was ever used.
- Isolation honoured: `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed or globbed; nothing outside `workspace/implementation/` was written.

## PRD-interpretation adjudications
1. **Acceptance returns the application, 200** — not the new LoanAccount/201; the account is discoverable via `GET /loan-accounts?application_id=`.
2. **Band position vs. state-machine order** — where §2.9 explicitly lists an endpoint in a band (e.g. band 14 merchant posture at draw settlement), the band number wins; where a precondition is not in any band (milestone posture at settlement, merchant posture at milestone claim), the state machine's own order governs. Claim therefore checks milestone state → project state → merchant `APPROVED` last.
3. **Consumer-signoff rule read generically** — band 17's "the verifying actor must be the owning `Consumer`" is applied to any verification decision on a `requires_consumer_signoff` milestone (not just the VERIFY branch), and a rescission from `VERIFIED` is consumer-only regardless of the flag.
4. **Reversal enforces the full band 23 condition** (`PAID_OFF` and `CHARGED_OFF` both block) since band 23 explicitly enumerates draw reversal, even though §3.8's prose only names `CHARGED_OFF`.
5. **"At least one settled draw" on a dispute is subsumed by band 53** — with no settled draws `settled_funded_cents` is 0, so any positive claim already yields `ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED`; no separate error code was invented.
6. **All five final draw figures open as `null`** (including `volume_tier_credit_bps`, whose scaffold `default: 0` contradicts its own "null until settlement" description) — PRD §3.7 prose wins.
7. **`completion_certificate_ref` is optional at the payload level**; its non-emptiness and the "every milestone CLAIMED or VERIFIED" clause are enforced only when the trade rule's `requires_completion_certificate` is true (band 29's final sentence), and vacuously pass for a project with no milestones.
8. **`expected_loan_account_version` is optional** on draw creation (§2.8: an omitted OCC field skips the check); `expected_merchant_version` is required on holdback adjustments and dispute resolution because both PRD passages state it is carried.
9. **Dispute `reopens_case_id` resolves in band 6** with `ERR_DISPUTE_NOT_FOUND` per §2.7's declared FK order, leaving band 41's `ERR_DISPUTE_NOT_REOPENABLE` for targets that exist but are ineligible.
10. **Unrouted paths/methods** use `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` (no catalogue entry exists for either) while still emitting the standard error envelope.

## Step 7: Run tests and iterate — 2026-09-04T01:26:00.000Z

All 8 parallel rounds pass 292/292.

## Summary

**Iterations run:** 2 (baseline sweep with 7 stable failures → fixes → clean sweep).

**Sweep 1:** 285/292 in all 8 rounds; the same 7 tests failed in every round (no flakiness, no reaping — all rounds completed normally).

**Tests deleted:** none. All 7 failures traced to STEP 2 (test artifact not faithfully expressing the PRD rule); no test asserted a scaffold-only or PRD-silent rule.

**Fixes applied to `test_suite/`:**

1. `test_09_compensating_invariants.py` — `test_the_merchant_ledger_movements_mirror_the_three_buckets`: removed a spurious unary minus on the reserve-movement term. PRD §3.10 requires the three ledger movements to re-sum to the claim (96002 + 1200025 + 1104023 = 2400050); the negation made a conservation invariant assert a non-conservation.

2. `test_10_entity_shapes.py` — `test_merchant_retrieval_of_unknown_id_reports_merchant_not_found`: replaced `assert "data" not in response.json()` with `assert set(response.json()["data"]) == {"error_id", "message"}`. PRD §2.2 explicitly puts `error_id`/`message` inside `data` on every error envelope, so the original assertion contradicted the PRD it was meant to check.

3. `test_13_validation_corners.py` — `test_a_pending_milestone_is_tolerated_when_the_trade_waives_the_certificate`: moved `certified_on` out of the exact-equality `assert_fields` into a clock-date prefix assertion (STEP 1c partial coverage). PRD §3.6 says only "stamps `certified_on` from the logical clock" and never pins date-vs-instant rendering; the suite already uses the prefix convention for the identically-worded `verified_on` (test_07 L230, test_10 L615).

4. `test_15_error_corners.py` — `test_a_payment_exactly_at_the_payoff_ceiling_closes_the_loan`: passed `201` to `validate_success`. PRD §4: "Endpoints that bring a new resource into existence answer with HTTP 201"; `POST /payments` mints a Payment, and every other payment-creation call in the suite already expects 201.

5. `test_15_error_corners.py` — `_acknowledged_second_offer_behind_a_funded_loan` (shared setup for the 2 KeyError failures): added `scenario = S.project(api, scenario)` before `S.project_with_milestones(api, scenario, ...)`. The builder short-circuits project creation when handed a truthy scenario, so an `activated_loan` scenario reached `add_milestones` with `scenario.project == {}` → `KeyError: 'id'`. This was the single upstream setup bug behind 2 of the 7 failures.

6. `test_16_access_control.py` — `test_the_merchant_is_refused_on_role_before_the_application_state_is_examined`: `status="ACTIVATED"` → `decision="ACTIVATED"`. PRD §3.4 pins the application's decision dimension to the field `decision`; there is no `status` field on a credit application.

**Fixes applied to `implementation/`:** none — no failure survived STEP 1/STEP 2 as an implementation defect.

**Orchestrator independent verification:** read all 8 `workspace/implementation/results.{1..8}.json` directly — each reports `passed: 292, failed: 0, total: 292, errors: 0, skipped: 0`. Artifacts confirmed present, not merely claimed.

**Step 8 decision:** Step 7 ran 2 iterations with 6 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) does NOT apply — Step 8 will run. Note that all 6 fixes were test-artifact repairs and there were 0 `implementation/` fixes and 0 deletions, so Step 8's expected diff is small: the only PRD-silence signals available are items 3 (`certified_on` rendering) and, weakly, 4 (payment creation status code).

## Step 8: Finalize PRD — 2026-09-04T01:37:00.000Z

Done. `PRD_FINALIZED.md` produced with two edits.

## Line counts
- `PRD.md`: 497 lines
- `PRD_FINALIZED.md`: 497 lines
- Delta: 0 lines added/removed (0.0%); 2 lines revised in place (0.40% of lines touched)

## Changes
- **§3.6 (Certification)** — revise — pinned that `certified_on` is stamped from the logical clock *as a full ISO 8601 UTC instant with three fractional digits, not as a bare calendar date* — `implementation/routes_project.py:284` (`project["certified_on"] = db.now()`), rendered via `implementation/serialize.py:180` → `_dt` → `util.fmt_dt` (`implementation/util.py:37-41`).
- **§3.2 (Licence verification)** — revise — same rendering pinned for `verified_on`, cross-referencing §3.6 — `implementation/routes_program.py:304` (`lic["verified_on"] = db.now()`), rendered via `implementation/serialize.py:90`.

## Per-edit pre-edit search log

**Edit 1 — §3.6 `certified_on`**
- (a) Subject: the `certified_on` field on `Project` — its value source, its wire rendering, and every write/clear of it.
- (b) Paths enumerated: `grep -rn certified_on implementation/*.py` → exactly 3 sites. `routes_project.py:80` (project creation, `None`); `routes_project.py:284` (certification, `db.now()` = logical-clock `datetime`); `serialize.py:180` (`_dt(...)` → `fmt_dt` → `%Y-%m-%dT%H:%M:%S.mmmZ`, `None` when falsy). Also read `util.py` (`fmt_dt` vs `fmt_date`), `store.py` (`db.now()` returns the clock `datetime`, `db.today()` returns a `date`), `routes_project.py:750` (the abandonment site) and `calc.py:283`.
- (c) Adjustment: scoped the new clause tightly to the *certification stamp* rather than to the field in general. The enumeration showed the abandonment path (`routes_project.py:750`) sets `completion_status = "ABANDONED"` but does **not** clear `certified_on`/`completion_certificate_ref`, contradicting the existing §3.6 abandonment sentence. That is a pre-existing PRD/impl divergence outside `<step_7_diff>`, so the sentence was left verbatim and the new clause makes no claim about the abandonment path or about the empty-at-creation value.

**Edit 2 — §3.2 `verified_on`**
- (a) Subject: the `verified_on` field on `MerchantLicense` — its value source and wire rendering — plus the wider question of which `*_on` fields in this impl are dates and which are instants.
- (b) Paths enumerated: `grep -rn "verified_on|verified_by_user_id" routes_program.py calc.py ops.py` → `routes_program.py:255/257` (filed licence, `None`), `routes_program.py:302-304` (both `VERIFIED` and `REJECTED` outcomes write `db.now()`), `serialize.py:90` (`_dt`). Then read all of `serialize.py` to classify sibling fields: `_dt`/instant → `approved_on`, `verified_on`, `certified_on`, `disclosure_delivered_at`, `disclosure_acknowledged_at`, `offer_expires_at`, `claimed_at`, `verified_at`, `response_due_at`, `merchant_responded_at`; raw date strings → `settled_on`, `opened_on` (dispute and alert), `resolved_on`, `posted_on`, `first_funding_on`, `last_payment_on`, `promo_expires_on`, `effective_from`, `expires_on`.
- (c) Adjustment: deliberately did **not** write a general rule such as "every `*_on` field is an instant" — the enumeration shows that would be false for `settled_on`, `opened_on`, `resolved_on`, `posted_on`, `first_funding_on`, `last_payment_on` (all `fmt_date`, and all already pinned as *dates* by existing PRD prose). The clause is confined to `verified_on` with an explicit "like the project's `certified_on` in §3.6" pointer, and applies to both `VERIFIED` and `REJECTED` outcomes, matching `routes_program.py:304` which stamps it unconditionally.

## Items judged to need no PRD edit
- **Item 1** (ledger conservation sign): `calc.chargeback_waterfall` + `routes_project.py:728-742` move reserve/receivable/write-off exactly as §3.10 already states, all three positive and re-summing to the claim. Pure fixture sign bug.
- **Item 2** (error envelope): `response.py:37-43` puts `error_id`/`message` inside `data`, exactly as §2.2 already specifies.
- **Item 4** (payment 201): `routes_credit.py:423` uses `created(...)` → `response.py:24` → 201, exactly as §4 already specifies. Verified all 13 `created()` callsites are creation endpoints, so §4's blanket 201 rule remains accurate.
- **Items 5, 6**: builder short-circuit and a nonexistent `status` field on credit applications — both contradicted PRD text that is already correct (§3.4 pins `decision`).

Noted but left alone (out of `<step_7_diff>` scope): §3.6's claim that abandonment clears `completion_certificate_ref` and `certified_on` is not implemented at `implementation/routes_project.py:750`. Orchestrator note: this is exactly the class of residual mismatch Step 9's full impl scan is designed to close, and it is carried forward as an explicit target for Step 9.

## Step 9: Complete PRD — 2026-09-04T02:20:00.000Z

Run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, per the known failure mode where a single one-shot Step 9 subagent emits a byte-identical copy. Partition: pass 1 = `app/util/errors/response/store/serialize/validate/routes_program`; pass 2 = `calc/routes_credit`; pass 3 = `ops/routes_project`. Each pass edited in place with surgical `Edit` calls (never a whole-file `Write`) and verified the prior passes' edits survived.

**Aggregate result:** `PRD_FINALIZED.md` 497 lines / 117,584 chars → `PRD_COMPLETED.md` 497 lines / 130,895 chars (**+13,311 chars**, +11.3%). 46 line-blocks revised. Zero new lines, paragraphs or sections — every change is an in-paragraph insert or revision. File still ends at `| ERR_PAYMENT_EXCEEDS_PAYOFF | 422 |`; 53 endpoint rows and 68 error rows intact.

**Total changes: 50 — 37 ambiguity-pins, 13 mismatch-revisions.**

### Pass 1 — 21 changes (15 ambiguity-pins, 6 mismatch-revisions)
`errors.py ERROR_STATUS` verified byte-for-byte identical to the §5 table (68 rows, same ids/statuses/order) — no edit needed there.
- §2.1 — revise — mismatch — merchant's own book now includes the merchant on a promotion enrollment read by its own identifier — routes_program.py:521
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — util.py:19-21
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the host's *real* clock, unrelated to `created_at`/`updated_at` — response.py:12 vs store.py:47
- §2.3 — revise — ambiguity — non-integer `limit`/`offset`, out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST`; empty-string param = omitted — validate.py:200-219
- §2.3 — revise — ambiguity — equal-`created_at` records tie-break on server creation sequence, so order is always insertion order — store.py:59-61
- §2.3 — revise — ambiguity — filters are exact string equality; unknown filter *value* matches nothing rather than erroring; unrecognised query params ignored; boolean filters accept `true/false/1/0` any case — validate.py:226-245
- §2.5 — revise — ambiguity — whole-month date advancement clamps the day down to the last day of the target month — util.py:69-75
- §2.6 — revise — ambiguity — `created_at`/`updated_at` come from the logical clock, not the host clock — store.py:47,53
- §2.9 #4 — revise — mismatch — dropped promotion-plan creation from the date-range band's guard list (plans carry no dates) — routes_program.py:86-117
- §2.9 #7 — revise — mismatch — trade-rule and promotion-plan list reads admit a `Merchant` without resolving `X-User-ID` (verified the other 30+ endpoints do resolve) — routes_program.py:70-79,120-135
- §2.9 #15 — revise — ambiguity — licence-already-decided precedes the terminated-merchant gate — routes_program.py:294-300
- §3.1 — revise — ambiguity — all seven trade-rule fields required, no defaults — routes_program.py:46-52
- §3.1 — revise — ambiguity — all ten promotion-plan fields required; `allowed_trade_types` must be a non-empty array — routes_program.py:89-98
- §3.1 — revise — mismatch — "readable by every role" → "every role except `Consumer`" — routes_program.py:72-73,122-123
- §3.2 — revise — ambiguity — merchant `state_code`/`contact_email` stored verbatim, only checked non-empty — routes_program.py:147-148
- §3.2 — revise — mismatch — *both* licence verification outcomes increment the licence `version` — routes_program.py:305
- §3.2 — revise — ambiguity — enrollment submission with no `UNVERIFIED`/`VERIFIED` licence → `ERR_LICENSE_NOT_VERIFIED`, after the posture gate — routes_program.py:330
- §3.2 — revise — ambiguity — `decision_note` retained internally, never a field on the merchant resource — routes_program.py:380 / serialize.py:49-75
- §3.2 — revise — ambiguity — direct `SUSPEND` records the supplied `reason_code` verbatim; `ANALYST_ACTION` only substitutes when omitted — routes_program.py:404
- §3.2 — revise — ambiguity — the `termination_recommended` gate fails as `ERR_INVALID_MERCHANT_STATE` after the posture gate; `termination_reason_code` left empty when none supplied — routes_program.py:417-421
- §4 intro — revise — ambiguity — trailing slash equivalent to none — app.py:18
- §5 intro — revise — ambiguity — transport-level ids outside the catalogue (`ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INTERNAL`/500); unparseable/non-object body is `ERR_INVALID_REQUEST`/400 regardless of `Content-Type` — app.py:31-73, validate.py:51-63

### Pass 2 — 14 changes (12 ambiguity-pins, 2 mismatch-revisions)
- §2.1 — revise — mismatch — merchant's own book includes the merchant on a loan account and on that account's payment list — routes_credit.py:323,431
- §2.5 — insert — ambiguity — pinned the *start* boundary of both trailing windows (earliest included date exactly 180 / exactly 90 days back) — calc.py:341-352
- §3.4 — insert — ambiguity — `ssn_last4`/`state_code` checked only for being non-empty strings — routes_credit.py:32,35
- §3.4 — insert — mismatch — a stored application never rests at `PENDING`; five disclosure-side fields plus `promo_disclosure_summary` open empty — routes_credit.py:111-132
- §3.5 — insert — ambiguity — `interest_at_risk_note` is server-composed prose restating `deferred_apr_bps` and `expiration_date` — routes_credit.py:210-213
- §3.5 — revise — ambiguity — `acknowledged_template_version` optional, checked only when supplied and only after the three-day deadline → `ERR_DISCLOSURE_TEMPLATE_MISMATCH` — routes_credit.py:224,238-241
- §3.5 — insert — ambiguity — fixed acceptance precondition order (decision → counter-offer flag → disclosure → offer expiry → merchant posture → DTI last) — routes_credit.py:258-281
- §3.5 — insert — ambiguity — the DTI breach still writes `REVOKED` + `REVOKED_DTI_BREACH` + version bump before raising `ERR_DTI_LIMIT_EXCEEDED`, an explicit exception to §2.9's no-side-effect rule — routes_credit.py:281-288
- §3.5 — insert — ambiguity — acceptance answers 200 with the updated application, not the originated loan account — routes_credit.py:312
- §3.8 — insert — ambiguity — pinned which enrollment "governs": earliest-created `ACTIVE` one whose closed window holds the clock date, else earliest-created `ACTIVE`, else the plan rate — calc.py:453-463
- §3.8 — insert — ambiguity — formula for a reserve target recomputed outside a settlement (trailing-180 volume × current tier rate, no in-flight draw) — calc.py:442-447
- §3.9 — revise — ambiguity — a reversed draw contributes twice: the advance at `settled_on` and an equal reduction at the reversal date — calc.py:160-168
- §3.9 — insert — ambiguity — a non-positive accumulated total yields exactly zero, never a negative accrual — calc.py:206-209
- §3.9 — insert — ambiguity — `accrued_deferred_interest_cents` reads zero once the promo is satisfied or capitalized — calc.py:212-215
- §3.9 — revise — ambiguity — cure threshold uses *pre-payment* balances and the cure is evaluated first, so a delinquent account paid in full ends at `PAID_OFF` — routes_credit.py:384,407-422; calc.py:511-513

### Pass 3 — 15 changes (10 ambiguity-pins, 5 mismatch-revisions)
- §3.6 — revise — mismatch — **the Step 8 carry-forward, now resolved**: abandonment no longer claims to clear `completion_certificate_ref`/`certified_on`; it overwrites `completion_status` only and those two fields are left exactly as certification wrote them. Also added `SUBSTANTIALLY_COMPLETE → ABANDONED` as a reachable hop — routes_project.py:749-751, serialize.py:179-180
- §2.8 — revise — mismatch — `expected_loan_account_version` is optional; omitted/null means no version check rather than a malformed request — routes_project.py:304-307,319
- §2.9 band 20 — revise — mismatch — guard list now includes milestone claim, and states milestone verification is deliberately outside the band (a `VERIFY`/`REJECT` may be rendered on an `ABANDONED` project's milestone) — routes_project.py:139,199,213-247
- §3.8 — revise — mismatch — reversal requires the account to be neither `PAID_OFF` nor `CHARGED_OFF`, and requires nothing of merchant posture — routes_project.py:515-516
- §3.10 — revise — mismatch — "at least one `SETTLED` draw" is not a separate check (zero `settled_funded_cents` refuses every claim via `ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED`); consumer scope measured against the named loan account, not the project — routes_project.py:560,584-588
- §2.10 — insert — ambiguity — a record's `version` increments exactly once per request however many cascade links touch it — ops.py:21-32
- §3.6 — insert — ambiguity — claim admissions ordered milestone state → project state → merchant posture — routes_project.py:194-205
- §3.6 — insert — ambiguity — rescission is Consumer-only regardless of `requires_consumer_signoff`, clears `verified_at`, carries the `SUBSTANTIALLY_COMPLETE → IN_PROGRESS` fallback — routes_project.py:232-255
- §3.6 — insert — ambiguity — certificate ref stored verbatim/null when the flag is false; a missing trade rule behaves like the false branch — routes_project.py:274-284
- §3.7 — insert — ambiguity — draw creation versions only the milestone and project — routes_project.py:379-381
- §3.8 — insert — ambiguity — settlement also recomputes the consumer's `existing_program_debt_cents` and increments the consumer's and project's `version` — routes_project.py:492-496
- §3.8 — insert — ambiguity — a denial versions only the draw, milestone and project — ops.py:82-92
- §3.8 — insert — ambiguity — reversal versions the draw, milestone, project and consumer in addition to account and merchant — routes_project.py:523-536
- §3.9 — insert — ambiguity — the seven sweep families run strictly in order over already-mutated state, so one run can move an account `PROMO_ACTIVE` → `DELINQUENT` → `CHARGED_OFF` and count it in all three — ops.py:169-259
- §3.10 — insert — ambiguity — a merchant response leaves the case at `MERCHANT_RESPONSE_PENDING` and is therefore repeatable while the window is open, overwriting `merchant_responded_at`/`response_type`/`evidence_ref` — routes_project.py:674-684

**Orchestrator final verification:** `PRD_COMPLETED.md` is 497 lines / 130,895 chars and differs from `PRD_FINALIZED.md` in 46 line-blocks — it is emphatically NOT a byte-identical copy, so the scan genuinely ran. Every `implementation/` file's mtime (00:30–00:55) predates the 01:25 clean sweep, confirming Step 9 edited documentation only and the verified 8×292/292 green result still describes the shipped code.

**PIPELINE COMPLETE.**
