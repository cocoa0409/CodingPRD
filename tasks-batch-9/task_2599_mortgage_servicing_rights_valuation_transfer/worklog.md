# Worklog — task_2599_mortgage_servicing_rights_valuation_transfer

## Step 1: Create task directory — 2026-09-03T17:49:13.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2599_mortgage_servicing_rights_valuation_transfer` and its `workspace/` subdirectory. Index 2599 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T19:17:21.000Z

All three scaffold artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1699

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**
- `SCAFFOLD.yaml` — 3,347 lines / 173 KB (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,844 lines / 183 KB (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 7,410 lines / 471 KB (single key `scaffold_corner_design`)

**Scaffold shape** — domain `mortgage-servicing-rights-transfer`, api_prefix `/msr`. complexity_profile: multi_party_negotiation + compliance_audit, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers]`, entity_topology graph, state_machine_shape parallel, role_model segregation_of_duties, consistency immediate.
- **15 entities**: Counterparty, ServicingPortfolio, Loan, AssumptionSet, RateCurveSnapshot, ValuationRun, BidPackage, TapeLine (junction), Bid, PurchaseAgreement, ApprovalRequest, ServicingTransfer, BorrowerNotice, ErrorResolutionCase, HedgePosition.
- **12 state machines**, including the parallel/compound `ServicingTransfer` (independent notice / data / pipeline dimensions with derived `readiness`), the cyclic `Bid` negotiation (counter/revise to a round cap), the cyclic `ErrorResolutionCase` (reopen window + escalation on the third reopen), and `RateCurveSnapshot` supersession that cascades ValuationRun → BidPackage → Bid.
- **11 calculations**: `msr_fair_value` (dual variant DETERMINISTIC_STATIC vs OAS_SHOCK_WEIGHTED), active_rate_curve_selection, effective_valuation_selection, reserve_price, purchase_price (per-stratum rounding then summation), tape_stratification, holdback_sizing, complaint_concentration_release (tiers at 25.00 % / 50.00 % with a 40 % remediation cap), counterparty_transfer_risk_score (pre-award vs post-transfer variant), notice_statutory_window, hedge_mark_to_market (per-instrument OAD).
- **48 ordered validations, 62 errors, 69 endpoints, 8 roles** (ValuationAnalyst, TransactionManager, SellerServicer/BuyerServicer entity-backed, AgencyApprover, ComplianceOfficer, HedgeDesk, PlatformAdmin — deliberately *not* a hierarchical override), 3 SoD pairs at priority 19, 3 OCC rules (`expected_portfolio_version`, `expected_bid_package_version`, `expected_purchase_agreement_version`), logical clock default `2026-08-01T00:00:00Z`.

**§1.8 difficulty design** — all 9 rule_ids × 2 differentiated instances = 18, every asserted figure derived with Decimal/ROUND_HALF_UP reference scripts (e.g. static value 171576 vs OAS 170962 on the 4-loan 40,000,200 pool; purchase price 472004; holdback 28320 / wire 443684).

**§1.9 corner design** — all 9 guide sections, 83 instances (67 full `test_recipe`s + 16 `excluded_because` stubs, each citing an existing §1.8 instance as `rule_id / name`): entities 12, state_machines 16, calculations 14, validations 13, endpoints 6, errors 7, rbac 7, cross_cutting_complexity_layers 7, consistency_model 1. Programmatic audit confirms **all 62 error ids are triggerable** somewhere across §1.8+§1.9, no duplicate instance names across the two design files, no forbidden concurrency vocabulary in any file.

**Adjudications made**
- 69 endpoints / 62 errors intentionally exceed the Expert band (20–32 / 18–30) because the scenario asks for "harder than expert level".
- Complaint tiers pinned at 25.00 %/50.00 % so boundaries are exactly hittable on a 4-loan pool; the bidder risk-score threshold 40 is *not* exactly reachable, so that boundary is asserted as 45 admitted / 37 refused rather than an exact-40 hit.
- Validation priority 14 was rewritten to enforce transfer-dimension ordering with a deliberate carve-out for `reconcile`, otherwise `ERR_ESCROW_NOT_MAPPED` (priority 31) would have been unreachable; similar reachability harmonisations were applied for `ERR_AGENCY_APPROVAL_PENDING` (13/23) and `ERR_MAX_REOPENS_EXCEEDED` (15/42).
- Header name normalised to `X-User-Role` in validation priority 2; `RateCurveSnapshot.base_rate_bps` range widened to 100–8000 to admit the shocked fixtures.
- `POST /msr/portfolios/{id}/loans` now declares `escrow_balance_cents?`, `suspense_balance_cents?`, `delinquency_bucket?`, `loss_mit_status?` as optional, matching their entity-level defaults (required for the defaults corner to be legal).
- Parent-aggregate captures (`notice_count`, `late_notice_count`, `approval_pending_count`, `winning_bid_id`) were moved off child-entity write responses onto reads of the owning entity — the lint's JSONPath resolution correctly caught these.

## Step 3: Copy shared files — 2026-09-03T19:17:44.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T19:40:00.000Z

Orchestrator truncation check: `wc -lc` = 482 lines / 102,301 chars; `## ` sections at lines 3/11/173/340/416 (§1–§5 all present); §5 contains exactly 62 `ERR_*` rows and the file's last line is a complete table row. Not truncated — no regeneration needed.

PRD complete and verified.

**Output:** `workspace/PRD.md` — **483 lines, 101,944 characters**, written in 11 chunked appends (`cat >> ... <<'PRDEOF'`, plus two programmatic appends for the two large tables). File ends on the final row of the §5 error table; no truncation, no trailing audit footer.

**Section list**
- `# Mortgage Servicing Rights Transfer API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Desk Participants and Role-Based Access Control · 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, Versions and the Logical Clock · 2.5 Money, Rates and Rounding Discipline · 2.6 Version Guards on Pricing-Sensitive Writes · 2.7 Nested Path Resolution · 2.8 Market-State Propagation: Curve Supersession and the Staleness Chain · 2.9 Completion and Termination Propagation · 2.10 Segregation of Duties · 2.11 Conserved Quantities · 2.12 Refusal Ordering and Discriminated Errors
- `## 3. Business Logic & Workflows` — 3.1 Onboarding Counterparties and Reading Transfer Risk · 3.2 Assembling the Pool and Freezing the Tape · 3.3 Assumptions, Rate Curves and the Fair-Value Model · 3.4 Bid Package Preparation: Stratification, Reserve and Publication · 3.5 Bidding and Negotiation · 3.6 Award, Consent Prerequisites and Settlement · 3.7 Executing the Transfer: Three Independent Work Streams · 3.8 Post-Transfer Error Resolution, Holdback Release and Closure · 3.9 Hedging the Servicing Asset
- `## 4. Endpoint Definitions` (4-column table, 69 rows)
- `## 5. Error Code Catalogue` (2-column table, 62 rows)

**Coverage confirmation (all machine-checked against SCAFFOLD.yaml)**
- Entities: 15 entity blocks / **145 field names**, all rendered.
- Endpoints: **69/69** paths present in §4 with method, description and exhaustive role list, including `POST /_clock/set_current_utc`.
- Errors: **62/62** in §5 with correct HTTP status, and **every one also used in §2/§3 prose** (zero table-only codes).
- Validations: all **48** priority-ordered rules rendered — global ladder in §2.12, local orderings restated at each workflow; all rule constants present (only scaffold-internal cross-references like `§1.7` / "rule 13" deliberately not carried over).
- Calculations: all **11** rendered in full prose including both `msr_fair_value` variants, both `counterparty_transfer_risk_score` variants, all constant tables (DQ multipliers, loss-mit surcharges, 4,000 bps reference, OAS scenarios/weights, capital tiers, penalty caps, OAD factors 4.5/6.0/5.5) and normative rounding order.
- State machines: all **12**, every `from`/`to` state token present, including the three parallel `ServicingTransfer` dimensions plus derived `readiness`, and all cascade/compensating transitions.
- Style scan: no `==`/`>=`/`+=`/`min(`/`round(` pseudocode, no fuzzy quantifiers, no scaffold meta-jargon ("reverse-reachability", "cascade A", "OCC", `MAX_NEGOTIATION_ROUNDS = 3" all rewritten), all `§` refs resolve to PRD sections.

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** Required set = 145 entity fields + 23 endpoint-only identifiers = **168 unique names; 0 missing**, all appearing verbatim in backticks (437 distinct backticked identifiers total).
- **Contract 2 — Rule Coverage: PASS.** 48/48 validations (with precedence), 3/3 optimistic-concurrency guards (`expected_portfolio_version`, `expected_bid_package_version`, `expected_purchase_agreement_version`, all 412), both segregation-of-duties clauses, all cascades (curve supersession depth-4 chain, completion propagation with its conditional link, termination unwind), all field-level defaults, and sibling-branch symmetry for both dual-variant calculations and every state-machine branch.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 that start with `/`, are a bare HTTP method, or combine method+path; every operation referred to by state transition, role+verb, or capability.

**Zero-Silence decisions**
1. `projection_years`: entity default 3 vs endpoint-required → "recorded as 3 when the caller does not supply it."
2. `primary_secondary_spread_bps`: same conflict → "recorded as 25 when not supplied"; stated explicitly that it enters no formula.
3. `scenario_values` under `DETERMINISTIC_STATIC`: entity says null, variant text says `{}` → chose **null** (entity field table is field-level authority).
4. Counterparty suspension's "no agreement naming it as buyer can be settled" has no error code and settle is outside that rule's scope → rendered suspension as forward-looking, enforced with `ERR_BIDDER_NOT_ELIGIBLE` at bid and at award; no settle-time code invented.
5. lock-tape's "at least one loan" precondition has no code → stated as a requirement with no code asserted.
6. submit-for-approval's "at least one approval request, all still `PENDING`" preconditions have no code → same treatment.
7. complete's "clock date has reached the transfer date" precondition has no code → same treatment.
8. `settled_at` appears in a side effect but is not a declared `PurchaseAgreement` field → omitted rather than inventing a field.
9. `price_cents` exists only inside `stratum_price_breakdown` → rendered explicitly next to `upb_cents` so the breakdown shape is unambiguous.
10. reconcile's equality precondition names only `ERR_ESCROW_NOT_MAPPED` → rendered as the stated check plus that code for the not-yet-swept case.
11. `remediation_cents`: field says "cumulative across resolutions" while the transition says "stored" → chose **accumulation** on each resolution.
12. `RESOLVED → ESCALATED` declares no counter change → stated that `reopen_count` stays at 2.
13. Holdback exhaustion *before* the indemnification period has run: transition conditions require both → stated explicitly that such a release lands in `HOLDBACK_RELEASED` (still clawback-able), not `CLOSED`.
14. Verification caught and fixed one invented code in the §4 preamble (`ERR_ROLE_NOT_PERMITTED` → the scaffold's actual `ERR_UNAUTHORIZED`); no invented identifiers remain.

## Step 5: Generate unit tests — 2026-09-03T20:25:13.000Z

Orchestrator placement check: `test_helpers/` and `test_suite/` are both at the task root; `find workspace -type d -name 'test_*'` is empty; 15 files in test_suite, 260 `def test_` functions.

Stage 1 and Stage 2 are complete and mechanically verified.

## Files written

`test_helpers/` (task root, 9 files, 1,232 lines) — `types.py` 23, `api_errors.py` 150 (all 62 ids + `ERROR_HTTP_STATUS` + `set_error_http_status_map`), `api_client.py` 384 (one method per endpoint, all 69), `constants.py` 278, `test_users.py` 131 (8 roles, entity-backed builders, malformed-auth builders), `assertions.py` 274 (envelope readers, `round_half_up` mirror, conserved-quantity assertions), `factories.py` 571 (one function per desk action), `fixtures.py` 422 (17 layered env builders + 12 pytest fixtures), `__init__.py` 161 (barrel, 211 exported names).

`test_suite/` (task root, `conftest.py` 27 lines + 14 test modules, 8,798 lines, **260 tests**):

| file | lines | tests |
|---|---|---|
| test_state_machines.py | 986 | 32 |
| test_calculations.py | 866 | 27 |
| test_entity_semantics.py | 840 | 35 |
| test_validations.py | 757 | 17 |
| test_complexity_layers.py | 724 | 19 |
| test_endpoint_contracts.py | 707 | 25 |
| test_error_conditions.py | 660 | 17 |
| test_rbac_and_duties.py | 634 | 16 |
| test_compensating_moves.py | 515 | 16 |
| test_cross_entity_gates_and_windows.py | 477 | 12 |
| test_refusal_priority_and_boundaries.py | 449 | 11 |
| test_valuation_and_pricing_variants.py | 447 | 14 |
| test_cascades.py | 409 | 9 |
| test_negotiation_and_transfer_dimensions.py | 327 | 10 |

## Coverage

- **Queue A: 18/18 instances translated, 0 skipped.** Every instance >=2 tests (range 2–9); 118 tests.
- **Queue B: 67/67 non-stub instances translated, 0 skipped on the PRD-first filter.** All 16 `excluded_because:` stubs carry exactly 0 tests and are named nowhere in the suite; 142 tests.
- Mechanical audit (`/tmp/verify_2599.py`): exactly one `Design:` tag per test (260/260), zero dangling/dual/mis-sectioned tags, zero stub tags, zero forbidden markers (`skip`/`xfail`/`TODO`/design-doc references), zero duplicate test names within any module.
- All 260 `PRD: "..."` docstring quotes verified byte-for-byte present in `workspace/PRD.md` by global substring check.
- `python3 -m py_compile` clean on all 24 generated `.py` files; `pytest --collect-only` collects 260 tests with no import or name errors. No file inside `workspace/` was written and `workspace/implementation/` was never touched (`__pycache__` cleaned up).

## Notable decisions

- **No instance was skipped**, but individual recipe assertions that failed the PRD-first filter were dropped rather than weakened, and are worth knowing because they are the places where a design index and the contract disagree — the PRD won every time: `scenario_values` is **null** (not `{}`) for a static run; the three transfer dimensions open at **`NOT_STARTED`** (not `UNMAPPED`/`NOTICES_PENDING`/`PIPELINE_PENDING`); a **partial holdback clawback is permitted** and leaves `HOLDBACK_RELEASED` (the index called it a refusal); an `INVESTOR` approval request must **omit** `agency_type`; the shape check precedes path-id resolution, so "404 before body validation" was not asserted; a second `lock-tape` and a client-supplied system field have no PRD-named outcome, so neither was pinned.
- **Timestamp equality was softened to instant prefixes plus `is_iso8601_timestamp`** wherever the PRD does not fix fractional-second rendering (`superseded_at`, `staled_at`, `current_utc`, `suspended_at`, `holdback_release_eligible_at`). Date-only fields and all cent values are asserted exactly.
- **Every derived literal was independently re-derived** from the PRD formulas by the owning agent before assertion — pool valuations 171576/209186/208484/175064/42894, per-stratum purchase price 472004 vs single-rounded bid value 472002, reserve 162997/166311/122248, holdback 28320 and 15% floor 70801, wire 443684, hedge marks -3510/-4680/-4290, notice lead days 31/2. All matched the indices.
- One fixture hazard found and worked around by two agents: `refresh_package`/`refresh_agreement` **reassign** the env key, so `assert x["version"] == env[...]["version"]` after a refresh is a tautology — affected tests snapshot the version first. Also `build_completed_transfer` skips `build_ready_transfer` when `env` already carries a `transfer_id`.
- One subagent died mid-write on an API error; I resumed the same agent with a computed to-do list rather than respawning, and its file finished at 724 lines / 19 tests covering all four of its instances (its two recovered instances are verified present and correctly tagged, though its own written skip report never arrived).

## Step 6: Generate implementation — 2026-09-03T20:25:13.000Z

Implementation complete and verified. Worklog-ready summary follows.

## Files written — `workspace/implementation/` (3,056 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | `set -euo pipefail`, `cd $(dirname $0)`, **guarded** `pip install` (`if ! python3 -c "import flask"`), `exec python3 app.py`. Executable. |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 64 | Blueprint registration, `json.sort_keys = False`, `strict_slashes = False`, handlers for `ApiError` / `HTTPException` / bare `Exception` (all emit the envelope), `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True, use_reloader=False)` |
| `core.py` | 548 | 62-entry `ERROR_HTTP` map, `ApiError`/`fail`, logical clock, 15-collection empty `DB`, `new_row`/`touch`/`sort_created`, envelope helpers, pagination, `authenticate()`, Decimal helpers (`rhu`, `rhu_int`, `floor_int`), strict field validators incl. `body_of()` allow-list, role-set constants |
| `calcs.py` | 444 | All 11 calculations + `active_curve`, `effective_valuation`, `included_lines`/`countable_lines`, `derive_readiness`, `custodial_funds_total` |
| `serial.py` | 311 | One explicit serializer per entity |
| `cascades.py` | 154 | 4-link curve supersession + hedge re-mark, completion cascade, termination unwind, newer-run supersession |
| `routes_a.py` | 216 | counterparties, portfolios, loans, lock-tape |
| `routes_b.py` | 139 | assumption-sets, rate-curves, valuation-runs |
| `routes_c.py` | 347 | bid-packages, stratify, tape-lines, publish, bids, counter/revise/award |
| `routes_d.py` | 308 | agreements, approval-requests, decide, settle, holdback releases/clawbacks |
| `routes_e.py` | 289 | servicing transfers, all three dimensions, notices, attest, complete |
| `routes_f.py` | 227 | error cases, hedge positions, hedge-effectiveness, `/_clock/set_current_utc` |

## Coverage

- **Endpoints: 69/69** — verified by count against PRD §4 (69 table rows) and path-by-path against the table.
- **Errors: 62/62** in `ERROR_HTTP` with the PRD §5 HTTP statuses; 3 distinct 412 ids (`ERR_STALE_PORTFOLIO_VERSION`, `ERR_STALE_BID_PACKAGE_VERSION`, `ERR_STALE_AGREEMENT_VERSION`).
- **Refusal ordering (§2.12)** implemented literally: auth -> authz -> shape -> path ids -> body ids -> ownership -> counterparty role -> the 10 state checks in their stated relative order -> 412 -> SoD -> the 29 business checks in the stated band-20 order. All three permissive carve-outs are in place (settle from `PENDING_APPROVALS` -> `ERR_AGENCY_APPROVAL_PENDING`; early reconcile -> `ERR_ESCROW_NOT_MAPPED`; reopen on `ESCALATED` -> `ERR_MAX_REOPENS_EXCEEDED`).
- **Calculations: 11/11** in `Decimal` (prec 60, `ROUND_HALF_UP`; `ROUND_FLOOR` for the remediation cap; sign-preserving half-up for hedge marks). No float arithmetic anywhere.
- **State machines: 12**, including the three parallel `ServicingTransfer` dimensions with derived `readiness` and the backward `ESCROW_MAPPED -> MAPPED` edge.
- **RBAC**: 8 roles via `X-User-ID`/`X-User-Role`, entity-backed ownership for Seller/BuyerServicer, 3 SoD rules.
- Logical clock only (boots at `2026-08-01T00:00:00Z`); no wall-clock reads.

## Smoke test result — all green

Seven phases run against fresh boots on ports 18601–18604:

1. **Happy path end-to-end** (counterparty -> ... -> complete -> error case -> holdback release -> clawback).
2. **Conserved quantities**: custodial total invariant across sweep / rollback / completion; holdback identity asserted after every money move.
3. **Cascades**: 4-link curve supersession with hedge re-mark, denial-driven termination unwind.
4. **Edge phase A**: `ERR_TAPE_EMPTY` on empty lock and on publish-after-full-exclusion, tape-line exclusion recomputing aggregates (`tape_upb 3000000 -> 2000000`), `ERR_TAPE_LOCKED`, `ERR_BIDDER_NOT_ELIGIBLE`, negotiation ceiling, `ERR_BID_DEADLINE_PASSED` vs `ERR_MAX_NEGOTIATION_ROUNDS` precedence, `ERR_BID_INVALID_STATE` on awarding a `COUNTERED` bid, 412 on a spent bid token.
5. **Edge phase B**: duplicate loan number, `ERR_RATE_CURVE_DATE_NOT_ADVANCING`, assumption-set immutability (no `version`/`updated_at`, `projection_years` default 3), duplicate/mismatched approval requests, `ERR_AGENCY_APPROVAL_PENDING`, SoD on decide, `ERR_APPROVAL_ALREADY_DECIDED`, conditional-approval holdback resize (12% -> 15% floor = 120000), `ERR_CONDITION_WAIVER_REQUIRED`, both `ERR_TRANSFER_DATE_TOO_SOON` limbs, `holdback_release_eligible_at` = 2026-09-15 + 180 = 2027-03-14, onboarding windows 2026-08-16 / 2026-10-15 and `ERR_ONBOARDING_CAPACITY_EXCEEDED` on the closed-window intersection.
6. **Edge phase C**: notice ownership-before-role-mismatch, effective-date mismatch, `ERR_LOAN_NOT_ON_TAPE`, `lead_days` 45 and the inclusive 15-day boundary both `COMPLIANT`, `ERR_NOTICE_COMPLIANCE_INCOMPLETE`, dimension ordering, rollback with no drift, `ERR_TRANSFER_NOT_READY` twice then completion at the transfer date, portfolio -> `TRANSFERRED` with `loan_count` 0 and custodial still 10000, second completion -> `ERR_TRANSFER_INVALID_STATE`.
7. **Edge phase D**: 412 -> SoD -> eligibility precedence on release; sticky breach flags; the full escalation ladder (reopen_count 0->1->2->`ESCALATED`, then `ERR_MAX_REOPENS_EXCEEDED` and `ERR_CASE_INVALID_STATE`); `ERR_REOPEN_WINDOW_EXPIRED`; release #1 gross 60000 / cap floor(24000) / charge 10000 / net 50000; release #2 charge 0 because the only case is no longer `RESOLVED` (step 4's status filter); partial clawback stays `HOLDBACK_RELEASED`, full clawback rewinds to `SETTLED`; `ERR_COMPLAINT_TIER_BLOCKS_RELEASE` at ratio 100.00.

**Cold-boot check**: every list endpoint returns `total_count=0` with no entities — nothing is seeded. Clock reads `2026-08-01T00:00:00.000Z`. Auth gates return 401/403, unknown paths 404, `limit=0` and `limit=101` both `ERR_INVALID_REQUEST`. `python3 -m py_compile *.py` clean on all 12 modules; `__pycache__` removed; all four smoke servers killed by explicit PID resolved from `ss -ltnp` (no broad pkill was used).

## Interpretation decisions where the PRD was ambiguous

1. **`scenario_values` is `null`** for `DETERMINISTIC_STATIC` (PRD prose over the scaffold's `{}`).
2. **Optional despite unconditional scaffold listing**: `projection_years` (default 3), `primary_secondary_spread_bps` (default 25), and `agency_type` for `INVESTOR` approval requests (must be omitted).
3. **Computed fields derived at read time** rather than stored: portfolio `loan_count` / `total_upb_cents` / `weighted_avg_note_rate_pct` / `custodial_funds_total_cents` / `valuation_freshness`; package `tape_upb_cents` / `tape_loan_count` / `stratum_count` / `bid_count`; counterparty `open_transfer_count`. This is what makes the custodial identity hold at *every* observable instant (including mid-cascade) and avoids spurious version bumps. `approval_pending_count`, `condition_count`, `notice_count`, `late_notice_count` and `transferred_loan_count` are **stored**, because the PRD names explicit recompute/stamp moments for them.
4. **Tape membership vs. package aggregates are different predicates.** `ERR_LOAN_NOT_ON_TAPE` checks and all post-award iteration use *included* lines regardless of loan status; the three package aggregates use *included AND loan `ACTIVE`* per the scaffold's aggregate definition. Consequence: an `AWARDED` package's `tape_loan_count` reads 0 after completion, which is the literal reading.
5. **Errors chosen where the PRD names none**: already-locked portfolio on lock-tape -> `ERR_TAPE_LOCKED`; zero-loan lock-tape -> `ERR_TAPE_EMPTY`; submit-for-approval with no requests -> `ERR_AGREEMENT_INVALID_STATE`; approval-request `agency_type` != portfolio `agency_type` -> `ERR_INVALID_REQUEST`; reconcile sum mismatch -> `ERR_ESCROW_NOT_MAPPED`; re-reconcile -> `ERR_TRANSFER_INVALID_STATE`; complete before the agreement's `transfer_date` -> `ERR_TRANSFER_NOT_READY`; suspending an already-`SUSPENDED` counterparty is accepted idempotently (no error code exists for it).
6. **`late_notice_count` only increments.** The PRD's "until it is superseded by a compliant one" has no decrement rule anywhere, so the literal counter semantics were kept — a late notice permanently blocks attestation.
7. **Client-supplied instants echo back verbatim** (`marketing_start_at`, `bid_deadline_at`, `counter_expires_at`); a parsed `datetime` is kept privately for comparisons. Server-generated stamps use the canonical 3-fractional-digit form.
8. **Cascades are not silent writes**: loan rows get `touch()` on map-escrow / rollback / completion, and re-marked `OPEN` hedges get `touch()` on curve publication, per §2.8.
9. `threaded=True` on `app.run` so a keep-alive connection from one client cannot block another during the concurrent 8-round sweep.

## Step 7: Run tests and iterate — 2026-09-03T21:05:00.000Z

Orchestrator verification of the sweep artifacts (per the known failure mode where a Step 7 agent claims a clean sweep without leaving results behind): all 8 `workspace/implementation/results.$i.json` exist, each ~77 KB, each parsing to `passed=260 / total=260`.

Done. Clean 8-round sweep: **260/260 passing in all 8 parallel rounds.**

## Summary

**Iterations run:** 2

Iteration 1 was deterministic, not flaky — the exact same 5 tests failed in all 8 rounds, which pointed at three real defects rather than load or timing.

**Tests deleted:** none. All 5 failing tests passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability).

**Fixes applied to `implementation/`:**
- `workspace/implementation/core.py`, `ERROR_HTTP` map — `ERR_MAX_NEGOTIATION_ROUNDS` was mapped to HTTP 422; PRD states 409 in two independent places (§3 prose: "refused with `ERR_MAX_NEGOTIATION_ROUNDS` (HTTP 409)", and the §5 status table row). Fixed to 409. I cross-checked all 62 error ids in `core.py` against the §5 table programmatically — this was the only mismatch, and `test_helpers/api_errors.py` already matched PRD exactly on all 62.

**Fixes applied to `test_suite/`:**
- `test_suite/test_negotiation_and_transfer_dimensions.py` — added an `_advance_data_to_sweep` helper and used it in `test_rollback_of_the_custodial_sweep_demotes_only_the_data_dimension` and `test_completion_refused_until_the_rolled_back_dimension_is_restored`. Both tests previously called `_advance_data`, which drives the data dimension all the way to `RECONCILED`, then issued a rollback. PRD is explicit: "a rollback attempted while `data_status` is anything other than `ESCROW_MAPPED` is refused with `ERR_TRANSFER_INVALID_STATE`" — so the implementation's 409 was correct and the *setup* violated the PRD precondition (STEP 2, test bug). The new helper stops at the custodial sweep, leaving `data_status` at `ESCROW_MAPPED`. Both tests' assertions were kept intact and are unchanged.
- `test_suite/test_rbac_and_duties.py` — added the missing `build_completed_transfer` import; the test failed with a bare `NameError` before issuing any request.

**Note on a PRD internal tension (no artifact change made):** §2.10 says readiness re-derivation applies to backward moves, illustrating with "rolling back the custodial sweep flips `readiness` from `READY` to `NOT_READY` again." That illustration is literally unreachable, because the same section defines `READY` as requiring `data_status == RECONCILED` while the rollback precondition admits only `ESCROW_MAPPED`. I resolved in favor of the two explicit normative sentences (the `READY` iff-definition and the rollback precondition) over the loose illustrative clause, and re-cited the rollback test's docstring to the precondition sentence it actually exercises. The implementation needed no change for this.

**Fixes applied to `test_helpers/`:** none needed.

## Step 8: Finalize PRD — 2026-09-03T21:22:00.000Z

`PRD_FINALIZED.md` is written. Only one of the three Step 7 items turned out to be a PRD issue; the other two were an impl-vs-PRD mismatch already fixed in the direction of the PRD, and a pure fixture bug.

**Line counts:** PRD.md 482 -> PRD_FINALIZED.md 482 (0.0% line delta; one line rewritten in place, ending at the same §5 error-catalogue boundary).

**Changes (1):**
- §3.7, transfer-dimensions preamble — revise — replaced the unreachable illustration "rolling back the custodial sweep flips `readiness` from `READY` to `NOT_READY` again" with "...re-derives `readiness` and leaves it `NOT_READY`", plus one clause noting the rollback is the only backward move on the three dimensions and is admitted only from `data_status` `ESCROW_MAPPED`, so a `READY` transfer can never take it — `implementation/routes_e.py:113-128` (rollback precondition + `derive_readiness`), `implementation/calcs.py:429-433` (`READY` iff all three terminal).

**Per-edit pre-edit search log:**
- (a) Subject: `readiness` re-derivation, and which dimension moves can run backwards.
- (b) Paths enumerated: `calcs.derive_readiness` (`calcs.py:429`) and every callsite — `routes_e.py:67` map-data, `:98` map-escrow, `:128` rollback-escrow, `:156` reconcile, `:180` transfer-pipeline, `:228` send-notice, `:268` attest-notices, `:281` complete; plus the transition guards on each of those endpoints (`notice_status` only NOT_STARTED->IN_PROGRESS->ATTESTED, `pipeline_status` only NOT_STARTED->PIPELINE_TRANSFERRED, `data_status` ladder with the single `ESCROW_MAPPED -> MAPPED` compensating edge at `:113`); `routes_d.py:233` (transfer created `NOT_READY`); `serial.py:235` (readiness serialised from the stored row); `cascades.py` grepped for `readiness` — no hits, so completion never rewrites it. Also cross-checked all 62 `ERROR_HTTP` entries in `core.py` against the §5 table programmatically: exact match, so no §5 edit.
- (c) Adjustment: my first draft said "the only backward move in the whole transfer," which could be read as covering the whole trade and would have falsely excluded the agreement's `HOLDBACK_RELEASED -> SETTLED` clawback rewind (§3.8) and the portfolio's `UNDER_CONTRACT -> TAPE_LOCKED` revert (§2.9). Re-scoped to "the only backward move any of the three dimensions has" before committing.

**Not patched (deliberately):** `ERR_MAX_NEGOTIATION_ROUNDS` — the impl was wrong (422) and Step 7 corrected it to the PRD's 409, which PRD.md already states twice; the impl now matches the §5 table on all 62 ids. The two `test_suite` fixes (rollback setup precondition, missing `build_completed_transfer` import) were fixture bugs against behavior the PRD already pins verbatim.

## Step 9: Complete PRD — 2026-09-03T21:20:00.000Z

Orchestrator verification (guarding against the known failure where PRD_COMPLETED.md comes back byte-identical to its source): `wc -lc` = PRD.md 482/102,301 · PRD_FINALIZED.md 482/102,545 · PRD_COMPLETED.md 484/118,594; `diff PRD_FINALIZED.md PRD_COMPLETED.md` yields 48 hunks; §4 still has 69 endpoint rows, §5 still has 62 error rows; the file ends on the last error-table row. The scan genuinely ran.

`workspace/PRD_COMPLETED.md` is complete. All three file-partitioned passes ran and each committed edits; no pass came back empty.

**Verification**
- `PRD_FINALIZED.md`: 482 lines / 102,545 chars -> `PRD_COMPLETED.md`: 484 lines / 118,594 chars (**+2 lines, +16,049 chars**)
- 48 diff hunks: 47 in-paragraph revisions + 1 inserted 2-line paragraph (§2.12, the only structural addition; no new sections)
- §4 endpoint table: 69 rows in both files. §5 error table: 62 rows in both files. File ends at the real boundary, `| ERR_CLAWBACK_EXCEEDS_RELEASED | 422 |`
- No duplicated-word or spacing artifacts; `SCAFFOLD*.yaml` and `worklog.md` were never read

**Totals: 37 ambiguity pins, 11 mismatch revisions.** Pass 1 = 8 (6/2), Pass 2 = 8 (5/3), Pass 3 = 32 (26/6).

### Pass 1 — core.py, serial.py, app.py
- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` count as empty; role names matched exactly and case-sensitively — core.py:308-315
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` reads the logical clock — core.py:220-225
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` are shape violations, whitespace tolerated; ties broken by a server-wide monotonic insertion sequence — core.py:253-272, core.py:210
- §2.3 — revise — ambiguity — filters compare serialised string equality, out-of-enum values return an empty page rather than 422; only `included` validates its value — core.py:282-289
- §2.4 — revise — ambiguity — the three client-supplied instants are echoed back verbatim, never renormalised — core.py:478-486
- §2.4 — revise — **mismatch** — the clock endpoint performs neither the identity nor the role check (PRD claimed it was "authorized for PlatformAdmin"); accepts a bare `YYYY-MM-DD`; may move backwards; `current_utc` is the only `data` field — routes_f.py:212-227, core.py:98
- §2.12 — revise — ambiguity — band-3 semantics: blank/`null` body reads as `{}`, non-object body is a violation, unknown body keys rejected while unknown query params are ignored, explicit `null` equals absent — core.py:354-393
- §2.12 — insert — **mismatch** — new paragraph for the two normative exceptions to band ordering: counter/revise test bid state before package state; two cross-field shape rules report `ERR_INVALID_REQUEST` from inside the business band — routes_c.py:231-287, routes_d.py:62-93, routes_d.py:180-244

### Pass 2 — calcs.py, cascades.py
- §2.6 — revise — ambiguity — the expected-version field is an integer >= 0; a negative value is a shape violation, not a 412 — core.py:411-421, routes_b.py:92
- §2.9 — revise — **mismatch** — the cascade close has no active-curve precondition and falls back to the position's own `entry_base_rate_bps`, driving mark and realised P&L to 0 — cascades.py:58-66
- §2.9 — revise — **mismatch** — termination reverts the portfolio only when *no* agreement on any of its packages is non-`TERMINATED` and the portfolio is still `UNDER_CONTRACT` — cascades.py:128-138
- §2.11 — revise — ambiguity — the custodial total spans every loan whatever its status and is derived per read, not stored — calcs.py `custodial_funds_total`
- §3.3 — revise — **mismatch** — curve ranking falls through `as_of_date` -> `created_at` -> insertion sequence, not `created_at` as the "only fallback key" — calcs.py:99
- §3.3 — revise — ambiguity — `scenario_values` are whole-cent integers serialised in scenario order, not alphabetically — calcs.py, app.py:23
- §3.4 — revise — ambiguity — reserve stamps 0 when the frozen UPB denominator is 0 instead of dividing — calcs.py:245
- §3.6 — revise — ambiguity — purchase price walks strata sorted by code point, over lines `included` regardless of loan status — calcs.py:269

### Pass 3 — routes_a.py … routes_f.py
- §3.1 — revise — ambiguity — suspend has no state precondition; re-suspending re-stamps and re-bumps — routes_a.py:56-66
- §3.1 — revise — ambiguity — `variant` is validated before the path id is resolved — routes_a.py:67-77
- §3.2 — revise — ambiguity — the `X-User-ID`<->`seller_id` bind applies only to `SellerServicer`; `PlatformAdmin` may name any seller — routes_a.py:78-98
- §3.2 — revise — **mismatch** — lock requires `DRAFT` (`ERR_TAPE_LOCKED` on a second lock), refuses an empty pool with `ERR_TAPE_EMPTY`, and the "freeze" is internal — the four readable aggregates stay live-derived — routes_a.py:169-186
- §3.4 — revise — **mismatch** — the bound run is resolved for existence only (never checked against the portfolio); tape-lock is reported before package state; stratify takes no body and returns the package — routes_c.py:18-86
- §3.4 — revise — ambiguity — tape-line PATCH returns the line, has no idempotency shortcut; package aggregates and `bid_count` are read-derived, so an awarded package reads 0 after completion — routes_c.py:109-131
- §3.4 — revise — ambiguity — a non-`STRATIFIED` package is refused `ERR_PACKAGE_INVALID_STATE` before any publication gate — routes_c.py:133-164
- §3.4 — revise — ambiguity — gate ordering wording tightened to match the coded sequence — routes_c.py:150-160
- §3.5 — revise — ambiguity — bid submission is not ownership-checked; `bidder_id` is never compared to `X-User-ID` — routes_c.py:172-212
- §3.5 — revise — **mismatch** — the `BUYER` role-mismatch check is first of the five, ahead of package state — routes_c.py:183-185
- §3.5 — revise — ambiguity — counter `counter_price_bps` is uncapped; the `round_number` clause is vacuous; package state checked after bid state — routes_c.py:231-287
- §3.6 — revise — ambiguity — award field bounds, `rep_warrant_days` comparison is band-3, package/bid state codes, foreign-package bid gets `ERR_BID_INVALID_STATE` — routes_c.py:289-346
- §3.6 — revise — ambiguity — all three `agency_type` conditions report `ERR_INVALID_REQUEST`, the third only after the `DRAFTED` check; duplicate detection counts requests in any status — routes_d.py:61-93
- §3.6 — revise — ambiguity — all three submit-for-approval failures report `ERR_AGREEMENT_INVALID_STATE` — routes_d.py:111-127
- §3.6 — revise — ambiguity — decide returns the `ApprovalRequest`, not the agreement; `decision_note` is unbounded; every decision bumps the agreement version — routes_d.py:128-177
- §3.6 — revise — **mismatch** — waiver-reference rules: absent vs blank vs wrongly-present, and where each is reported — routes_d.py:180-244
- §3.6 — revise — ambiguity — settle answers with the agreement, not the transfer — routes_d.py:180-244
- §3.7 — revise — ambiguity — every repeated dimension step is `ERR_TRANSFER_INVALID_STATE`; rollback lands in `MAPPED`, so the mapping template can never be re-chosen — routes_e.py:62,80,113,141,170,251
- §3.7 — revise — ambiguity — an unknown `loan_id` is `ERR_LOAN_NOT_FOUND` ahead of ownership/state/sender/date/tape; on-tape reads the `included` flag only — routes_e.py:195,211-214
- §3.7 — revise — **mismatch** — `late_notice_count` never decrements, so one late notice bars attestation permanently; attest takes no body, is not ownership-checked, and requires `NOTICES_IN_PROGRESS` first — routes_e.py:224-225, 251-263
- §3.7 — revise — ambiguity — map-data accepts only `mapping_scheme`; ownership precedes state on every step of the dimension — routes_e.py:52-63
- §3.7 — revise — ambiguity — map-escrow takes no body, sweeps by `included` flag regardless of loan status, and version-bumps each swept loan — routes_e.py:75-93
- §3.7 — revise — ambiguity — rollback's `reason` is mandatory, non-blank, unbounded; restored loans are version-bumped — routes_e.py:106-123
- §3.7 — revise — ambiguity — an already-`RECONCILED` transfer gets the repeat guard; a swept-total mismatch reuses `ERR_ESCROW_NOT_MAPPED` — routes_e.py:141-152
- §3.7 — revise — ambiguity — transfer-pipeline takes no body and counts by `included` flag alone — routes_e.py:162-181
- §3.7 — revise — ambiguity — complete takes no body, is not ownership-checked, re-derives readiness, and reuses `ERR_TRANSFER_NOT_READY` for the too-early date (not `ERR_TRANSFER_DATE_TOO_SOON`) — routes_e.py:274-286
- §3.8 — revise — ambiguity — a case may be opened while the transfer is `IN_PROGRESS`; `ERR_LOAN_NOT_FOUND` precedes the tape test; deadlines are instants preserving time of day; breach tests are strict — routes_f.py:27-52
- §3.8 — revise — ambiguity — acknowledge takes no body; resolve requires integer `remediation_cents` >= 0 and a non-blank unbounded note; ownership precedes case state — routes_f.py:74-114
- §3.8 — revise — ambiguity — reopen window is date-only and 60 days exactly still qualifies; reopen is not ownership-checked; only `RESOLVED`/`ESCALATED` reach the window test — routes_f.py:117-128
- §3.8 — revise — ambiguity — escalation clears neither timestamp; `resolution_note`/`remediation_cents` survive both moves; an escalated case's window still measures from the prior resolution — routes_f.py:129-139
- §3.9 — revise — ambiguity — a hedge may be opened against a portfolio in any status, with no ownership check; the curve error follows portfolio resolution — routes_f.py:144-161
- §3.9 — revise — ambiguity — `current_base_rate_bps` is null when no snapshot is `ACTIVE`; the read never fails — routes_f.py:195
- §3.9 — revise — **mismatch** — close takes no body and `ERR_HEDGE_ALREADY_CLOSED` precedes the curve check; the cascade close differs from the manual close in its curve fallback — routes_f.py:199-208, cascades.py:58-66

**Notable non-changes** (impl already pinned uniquely by PRD prose): the five-step holdback release ladder and its 40 % truncated cap, the hedge mark-to-market formula and duration factors, the notice `lead_days`/compliance arithmetic, the conserved-quantity identities, and the entire §4/§5 tables.

--- PIPELINE COMPLETE: Step 9 wrote workspace/PRD_COMPLETED.md ---
