# Worklog — task_0823_special_assessment_district

## Step 1: Create Task Directory — 2026-07-10T13:28:00.000Z

Created `tasks/task_0823_special_assessment_district/` and `tasks/task_0823_special_assessment_district/workspace/`. Directory pre-assigned by the invoking command (no auto-scan of ./tasks).

## Step 3: Copy Shared Files — 2026-07-10T13:28:05.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0823_special_assessment_district/workspace/INSTRUCTION.md` (1424 bytes). Performed early since it has no dependency on Step 2.

## Step 2: Generate Scaffold — 2026-07-10T13:55:00.000Z

All three scaffold artifacts are generated, parse cleanly under `yaml.safe_load`, and pass `scaffold_lint.py` with `VERDICT: clean lint` (330 §1.8/§1.9 calls checked; all FK reverse-reachability satisfied).

## Summary

**Task:** `/home/ubuntu/github/CodingPRD/tasks/task_0823_special_assessment_district/` — Special Assessment District & Improvement Bond (Expert).

Files written:
- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (`scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (`scaffold_corner_design`, §1.9)

**Complexity profile:** Pricing-engine primary + Compliance/audit secondary; flat/self-referential topology (Parcel has `parent_parcel_id`); branching state shape; peer-roles; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency.

**Entity model (10):** AssessmentDistrict → Parcel (self-referential via subdivision) → {ProtestFiling, Installment, PayoffQuote, Lien, ForeclosureAction}; AssessmentRoll and ImprovementBond hang off District; Payment hangs off Installment. Money ledger flows through `Parcel.remaining_principal_cents`.

**State machines (8):** District (branching fork FORMED/ABANDONED), AssessmentRoll (DRAFT→CONFIRMED→SUPERSEDED, reassessment path), ImprovementBond (AUTHORIZED→ISSUED→{CALLED,RETIRED,DEFAULTED}), Parcel (ACTIVE⇄IN_FORECLOSURE cycle + SUBDIVIDED/PAID_OFF/WITHDRAWN), Installment (SCHEDULED→DUE→{PAID,DELINQUENT}→…), PayoffQuote, Lien, ForeclosureAction (JUDGMENT→{SALE,REDEEMED} fork). 1 concurrency rule: OCC on `Parcel.version` for payoff-quote create-with-supersede (412).

**Calculations (6):** apportionment (waterfall, floor-then-distribute, dual variant by benefit-units/land-area/front-footage), amortization_schedule (level debt service, non-linear), payoff_quote (IMMEDIATE vs NEXT_CALL_DATE dual variant), delinquency_charges (penalty + monthly redemption interest), protest_ratio (strict-`>` boundary), subdivision_reallocation (benefit-unit conservation). All formula constants declared with concrete values (top-level `constants:` block + per-calc `constants:`; verified no undeclared symbols). Numeric asserts computed exactly in Python (e.g. debt service 777027, apportionment remainder 3333334/3333334/3333333, payoff 5655000 vs 5880000, delinquency penalty 105000/redemption 15750).

**Endpoint count: 34** (20 writes incl. `/_clock/set_current_utc` with 2026-03-01 default, 14 reads). **Error catalog: 29.** **Roles: 4** (DistrictAdministrator, CountyTreasurer opaque; ParcelOwner entity_backed:Parcel; Auditor opaque). **Validations: 22** ordered rows.

**§1.8:** 9 rules × 2 = **18 instances**. Each Difficulty Rule's differentiation clause is honored across different entity domains/modes/pairs (e.g. dual-variant on Parcel-apportionment vs PayoffQuote; combinatorial mode-a amortization vs mode-b rounding; Parcel cycle vs Foreclosure fork; cascades from payment vs roll-confirm; conserved money vs benefit-units).

**§1.9:** **22 active corner instances** across entities/state-machines/calculations/validations/endpoints/errors/rbac/OCC/consistency, plus **4 `excluded_because` stubs** pointing at their covering §1.8 instances.

One design adjustment during generation: removed the honor-time `ERR_QUOTE_EXPIRED` temporal check (it collided non-deterministically with the lazy `QUOTED→EXPIRED` transition); an expired quote now honors to a deterministic `ERR_INVALID_QUOTE_STATE`. Also added an `ImprovementBond ISSUED→RETIRED` transition to close the enum (RETIRED had no producer).

**Orchestrator verification:** `yaml.safe_load` clean on all 3; SCAFFOLD keys = scenario, domain_name, api_prefix, complexity_profile, constants, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. endpoints=34, errors=29, entities=10.

## Step 4: Generate PRD — 2026-07-10T14:05:00.000Z

All contracts pass. The PRD is complete.

## Summary

Generated `/home/ubuntu/github/CodingPRD/tasks/task_0823_special_assessment_district/workspace/PRD.md` from the scaffold.

**Sections written:**
- §1 Introduction (3 paragraphs, pricing-engine-in-a-compliance-ledger framing)
- §2 Global Specs: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Properties/Versioning, 2.5 Nested Path Validation, 2.6 Monetary Precision, 2.7 Logical Clock & Lazy Promotion, 2.8 OCC on Payoff Quotes, 2.9 Cascading Consistency & Ledger Conservation, 2.10 Validation Ordering
- §3 Business Logic (9 lifecycle subsections): District Formation/Protest, Parcels/Subdivision/Consolidation, Roll/Apportionment, Bond/Issuance/Amortization, Installments/Payments/Reversals, Delinquency/Redemption Interest, Prepayment/Payoff Quotes, Foreclosure/Redemption, Liens/Disclosure
- §4 Endpoint table (4 columns), §5 Error table (2 columns)

**Endpoint count documented: 34** (matches scaffold exactly).

**Coverage:** 10 entities; 8 state machines (District, Roll, Bond, Parcel, Installment, PayoffQuote, Lien, ForeclosureAction — all transitions incl. forks FORMED/ABANDONED and SALE/REDEEMED); 6 calculations (apportionment, amortization_schedule, payoff_quote with both IMMEDIATE/NEXT_CALL_DATE variants, delinquency_charges, protest_ratio, subdivision_reallocation) rendered as precise prose; 29 errors; 4 roles with identity translation (DistrictAdministrator/CountyTreasurer/Auditor opaque, ParcelOwner entity_backed:Parcel); 1 concurrency rule.

**Concrete constants carried into prose:** GRACE_DAYS 30, penalty 10% (0.10), monthly redemption interest 1.5% (0.015), foreclosure threshold 3, quote validity 30 days, 30/360 day count with 360 basis, default coupon 500 bps (5.00%), term 10 years, reserve 10% (0.10), admin fee 0 bps, prepayment premium 3% (0.03), round-half-up whole cents.

**Hard Contracts:**
- Contract 1 (Field-Name Coverage): every entity field + request_body/query_param/path_param identifier verified present in backticks — **PASS**
- Contract 2 (Rule Coverage): all transitions, calculations, validations paired with error_ids, OCC rejection (write_endpoint + `expected_parcel_version` + `ERR_STALE_PARCEL_VERSION`/412), cascades, sibling-branch symmetry, priority ordering expressed — **PASS**
- Contract 3 (§3 Path Purity): zero backtick tokens starting with `/` or bare HTTP methods in §3 — **PASS**

**Ambiguities resolved:**
1. Disclosure report output fields (`annual_installment_cents`, `next_due_date`, `lien_status`, `foreclosure_status`) had names but no pinned semantics in the scaffold — described them reasonably (current annual installment amount due; earliest not-yet-paid due date; status reflections) without inventing hard numeric contracts.
2. Foreclosure `advance` authorizes both DistrictAdministrator and CountyTreasurer at the endpoint level, but the state machine assigns specific actors per transition — expressed both (endpoint authorizes both; prose notes noticing/judgment/cancellation as administrator actions, sale/redemption as treasurer actions).
3. Delinquency base was stated two ways (state-machine `amount_due_cents "(base before penalty)"` vs calc `principal+interest+admin`) — used the calc's explicit definition since the note reconciles them.

**Orchestrator verification (guards against the stall-continuation race):** PRD.md = 282 lines. All 34 scaffold `method+path` pairs found verbatim in PRD; endpoint table has exactly 34 method rows. All 29 scaffold error ids present in PRD. PRD endpoint count == scaffold endpoint count ✓

## Step 5: Generate Unit Tests — 2026-07-10T14:25:00.000Z

All files compile and the suite collects. Here is the summary.

## Summary

Generated complete test infrastructure and a claim-driven test suite for the Special Assessment District API, translating **every** non-stub design-index instance. All 58 tests collect cleanly and every docstring carries a verbatim PRD citation (validated: a distinctive ≥8-word substring of each citation survives a literal grep of `PRD.md`, including backticked field/error names and bold thresholds) plus exactly one `Design:` tag.

### Files written
`test_helpers/` (Stage 1): `__init__.py`, `types.py`, `api_client.py` (35 endpoint methods), `api_errors.py` (29 errors + framework status-map registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque role headers + `make_parcel_owner_headers` for the `entity_backed:Parcel` ParcelOwner role), `fixtures.py` (composite lifecycle builders — `setup_formed_district`, `setup_confirmed_roll`, `setup_issued_bond`, `setup_foreclosure_at_judgment`, plus list-and-find readers for entities with no `GET /{id}` route).

`test_suite/` (Stage 2): `conftest.py` + 6 domain-named files (`test_01_formation_and_apportionment` … `test_06_access_and_state_guards`).

### Coverage (nothing skipped)
- **All 18 §1.8 difficulty instances → 2 tests each (36 tests).** Both tests per instance assert distinct facets of the same instance (e.g., dual-variant apportionment split into BENEFIT_UNITS vs LAND_AREA; the delinquency grace boundary tested at due+30 succeeds and due+29 rejects; foreclosure JUDGMENT forked into SALE-defaults-bond and REDEEM-returns-parcel-to-ACTIVE).
- **All 22 active §1.9 corner instances → 1 test each (22 tests).**
- **The 4 `excluded_because` §1.9 stubs were NOT translated** (verified each `difficulty_instance` cross-reference resolves to a real §1.8 `name:`: `bond_issue_blocked_without_confirmed_roll`, `payoff_quote_blocked_when_district_not_formed`, `installment_year_discrete_point_collision`, `bond_amortization_window_continuous_overlap` — all present).

### PRD-first filter
No instance failed the two-condition filter; every one has verbatim PRD coverage that uniquely derives the asserted outcome, so **zero instances were skipped**. The one error-precedence instance (`state_beats_fiscal_on_cancelled_installment_payment`) is asserted with an exact `error_id` rather than `validate_error_is_one_of`, because PRD §2.10 explicitly commits to the priority order (state-409 before fiscal-422) — the silence-pattern relaxation does not apply.

### Key fixture-correctness measures
- Fixtures build all state through declared endpoints only (server seeds nothing).
- Distinct parcel owners get distinct identities; ownership-gated ParcelOwner calls (protest filing) thread the real `parcel["id"]` via `make_parcel_owner_headers`.
- All time-dependent tests drive `/_clock/set_current_utc` (grace/delinquency, quote expiry, DUE promotion) rather than wall-clock; pre-computed literal expected values were copied verbatim from the design indices.

No `examples/` directory, no `pytest.mark.skip/xfail`, and no test walks `SCAFFOLD.yaml` directly.

## Step 6: Generate Implementation — 2026-07-10T14:25:00.000Z

Compile is clean (the exit 144 is the known pkill self-match, harmless). The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_0823_special_assessment_district/workspace/implementation/`.

### Files written
- `start.sh` — reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec python3 app.py` in foreground.
- `requirements.txt` — `flask==3.0.3`.
- `app.py` — app factory, registers 10 blueprints, `ApiError` handler, `before_request` hook running lazy promotions.
- `store.py` — in-memory dicts (10 collections), logical clock (default `2026-03-01T00:00:00Z`), id/seq/versioning, serialization, query helpers. No seeding.
- `util.py` — `round-half-up` via exact `Fraction` (away-from-zero), 30/360 day count, `add_years`/`add_days`, ISO-8601 parse/format (3 fractional digits + `Z`).
- `calc.py` — apportionment/subdivision waterfall (floor-then-distribute), level debt-service amortization (final year absorbs drift), payoff figures (IMMEDIATE vs NEXT_CALL_DATE), delinquency charges, foreclosure/grace/validity constants.
- `logic.py` — lazy `SCHEDULED→DUE` / `QUOTED→EXPIRED` promotion, lien recording, installment generation/cancellation, parcel PAID_OFF cascade, principal debit, bond CALLED/RETIRED reconciliation.
- `web.py` — error catalogue + status map, response envelope (`meta`/`response_type`/`data`), `X-User-ID`/`X-User-Role` auth decorator, ownership check, pagination (`limit`/`offset`/`total_count`/`has_more`), body/type validators.
- `fetch.py` — path lookups raising the correct per-resource 404.
- `routes/` — 10 blueprints (`districts`, `parcels`, `rolls`, `bonds`, `installments`, `payments`, `quotes`, `foreclosures`, `liens`, `clock`).

### Route count
**34 registered routes** (excluding static), asserted programmatically — matches the spec exactly.

### Implementation notes
- Money is integer cents throughout via `Fraction`; round-half-up is away-from-zero. Apportionment and subdivision floor-then-distribute (remainder cents by weight DESC, then creation seq ASC) so shares reconcile exactly; amortization pins ascending-year order with the final year absorbing rounding drift (verified: principal components sum back to P0).
- All time logic reads the logical clock; `created_at`/`updated_at`/business dates use it, so ordering is deterministic (internal `_seq` breaks ties). Lazy promotions do not bump `version`.
- Validation precedence follows PRD §2.10 (auth → authz/ownership → existence → OCC 412 → state 409 → referential → business constraints → temporal → payment fiscal → generic). OCC on payoff-quote create compares `expected_parcel_version` before the version-incrementing create.
- Cascades bump `version`+`updated_at` on every touched record; `ProtestFiling` and `Payment` are version-less ledger rows.

### Smoke tests (all passed, in-process)
Boot on a scratch port returned correct 401/404/201 envelopes. End-to-end runs verified: exact apportionment (750000/250000 for 3:1), amortization + principal conservation, delinquency penalty/redemption-interest math, OCC 412 + quote voiding + IMMEDIATE<NEXT_CALL_DATE accrual, subdivision principal conservation, foreclosure threshold + actor-RBAC (admin blocked from SALE), REDEEMED and SALE branches (bond→DEFAULTED, liens→FORECLOSED), district abandonment cascade, cross-owner protest 403, and the disclosure report.

**Orchestrator verification (guards against the Step-6 partial-write silent gap):** `compileall` clean; `app.py` present; all 10 route modules present; live `url_map` route count = 34 == scaffold endpoint count ✓. Test side: 58 tests collected; all 58 carry a `Design:` tag; 0 tags point to non-existent instances; 40 distinct instances covered (18 §1.8 + 22 §1.9) ✓

## Step 7: Run Tests and Iterate — 2026-07-10T14:35:00.000Z

All 8 rounds passed cleanly on the first sweep. The task is already in a fully green state.

Summary:
- Iterations run: 1 sweep (8 rounds, 2 waves of 4).
- Result: every round reported `passed=58 total=58`. No failing tests in the union across all 8 rounds.
- No tests deleted, no `test_helpers/` fixes, no `implementation/` fixes were needed.

Final round-by-round:
```
round 1: passed=58 total=58
round 2: passed=58 total=58
round 3: passed=58 total=58
round 4: passed=58 total=58
round 5: passed=58 total=58
round 6: passed=58 total=58
round 7: passed=58 total=58
round 8: passed=58 total=58
ALL 8 ROUNDS GREEN
```

The implementation at `workspace/implementation` is stable — the exit condition (all 8 rounds `passed == total`) is met with no changes required.

### Orchestrator verification of the clean first-sweep pass

A zero-fix first sweep is indistinguishable, from the summary alone, from a silently-broken sweep. Independently verified:

1. **All 8 `results.{i}.json` exist and parse.** Each has `passed=58 total=58`, `len(tests)=58`. Aggregate status counter across all 8 rounds = `{'passed': 464}` — **zero** `error`/`failed`/`skipped` statuses. This rules out the "every test ERRORed at boot, runner reported 0 failures" masquerade.
2. **Tests genuinely executed** — real test names present (`test_apportionment_by_benefit_units_assigns_expected_principal`, …), not placeholder/collected-only entries.
3. **Route count already asserted at Step 6** (34 == 34), ruling out the unrouted-endpoint silent gap where missing routes yield 0 test failures.
4. **Negative control (mutation test):** flipped `DELINQUENCY_PENALTY_PCT` in `calc.py` from `Fraction(1,10)` (10%) to `Fraction(11,100)` (11%) and ran one round → `passed=57 total=58`, with exactly `test_delinquency_charges_penalty_and_redemption_interest` failing. The suite has teeth; the green is not vacuous.
5. **Restore verified:** `calc.py` diffed byte-identical to the pre-mutation backup; a post-restore round returned `passed=58 total=58`. `__pycache__` cleared. No mutation residue remains in the task tree.

**Step 8 skip condition MET** (0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes) → Step 8 skipped, no `PRD_FINALIZED.md` produced. Step 9 proceeds from `PRD.md`.

## Step 8: Finalize PRD — SKIPPED — 2026-07-10T14:50:00.000Z

Skipped per the skill's skip condition: Step 7 exited on the first 8-round sweep with zero iterations beyond the baseline (0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes). `PRD.md` already uniquely determined every behavior the implementation exhibits at the sites Step 7 would have targeted. No `PRD_FINALIZED.md` is produced; Step 9 takes `PRD.md` as its source.
