# Worklog — task_2581_online_travel_agency_model_rate_parity_administration

## Step 1: Create task directory — 2026-09-03T15:11:36.273Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2581_online_travel_agency_model_rate_parity_administration` and `.../workspace` (pre-assigned path from the invocation; no index auto-allocation performed, per instruction that 32 pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-03T16:12:00.000Z

Task 2581 scaffold is complete and lints clean.

### Verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    86
  §1.1 entities declared:     17
  §1.8 instances scanned:     19
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  952

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Files

- `SCAFFOLD.yaml` — 2306 lines / 161 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1359 lines / 76.5 KB, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2190 lines / 111.7 KB, single key `scaffold_corner_design`

SCAFFOLD.yaml holds §1.0–§1.7 only (no design keys); the scenario text is stored verbatim as a block scalar.

### SCAFFOLD.yaml shape

`domain_name: ota-model-rate-parity`, `api_prefix: ""`. Profile: pricing_engine + compliance_audit, layers `dual_variant_calculation / cascading_side_effects / selector_policy / optimistic_concurrency`, topology `graph`, state shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.

- **17 entities**: Market, Supplier, ModelAgreement, Certification, RatePlan, Offer, DirectRateObservation (immutable, no version), ParityCase, CommissionOverride, PlacementAgreement, RankingRun, RankingEntry (immutable), Package, PackageComponent (junction), Booking, DisputeCase, SupplierScorecard.
- **13 state machines**, two of them on Booking's independent `payment_status` / `fulfillment_status` dimensions.
- **2 concurrency rules**: `offer-create-stale-rate-plan` (`POST /rate-plans/{id}/offers`, `expected_rate_plan_version`) and `package-price-stale-package` (`POST /packages/{id}/price`, `expected_package_version`), both 412 `ERR_STALE_VERSION`.
- **9 calculations**: `offer_sell_price` (merchant gross-up vs agency commission, override selector), `package_pricing_and_allocation`, `parity_breach_evaluation`, `ranking_score`, `refund_passthrough_due`, `dispute_settlement_total`, `dispute_liability_split` (PRELIMINARY/BINDING), `supplier_composite_score` (PROVISIONAL/FINAL), `placement_slot_capacity`.
- **33 validations** (priority 1–33), **86 endpoints** (POST/GET only — no PATCH/PUT/DELETE anywhere), **74 errors**, **6 roles** (PlatformAdmin, CommercialManager, ComplianceOfficer, ParityAnalyst, SupplierUser [entity_backed], BookingAgent).

### §1.8 — 19 instances across all 9 rule_ids

dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 2 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 2.

### §1.9 — 66 instances / 9 sections (49 with recipes, 17 `excluded_because` stubs)

entities 12 · state_machines 11 · calculations 11 · validations 9 · endpoints 4 · errors 7 · rbac 6 · cross_cutting_layers 5 · consistency_model 1.

The five sections finished this session: **endpoints** (paid-placement `computed_read` at final_score 95.50, ranking publish metadata, chargeback simulation as `conditional_action` incl. `ERR_PAYMENT_NOT_CAPTURED`, both-targets booking rejection); **errors** (duplicate `EU-PAR`, empty ranking pool, MARKUP_PCT under AGENCY, dispute on a fully refunded booking, early scorecard finalize + clock advance to a success, opaque publish with names revealed, publish without disclosure_version); **rbac** (two exclusive-op denials in opposite directions, SupplierUser cross-supplier scope violation with reads still open, undeclared role → 401 ahead of existence checks, publish shared between CommercialManager and SupplierUser, same `X-User-ID` proposing then approving an override → 403); **cross_cutting_layers** (both OCC rules with stale-then-refresh, a `selector_policy` instance, and stubs for cascading_side_effects / dual_variant_calculation); **consistency_model** (`immediate`, asserting the price response equals the subsequent GET and the suppress cascade is visible with no intervening call).

### Design adjudications

- **Override selector ranks scope before magnitude.** Plan-scoped 0.18 beats supplier-wide 0.20; base 0.15 is never consulted. Tie-break is `created_at ASC`, and the formula states `id` is never consulted.
- **Mediation fee tier is keyed on `refund_due_cents`, not the settlement total** — the availability clamp reduces a 60000 claim to 24240, keeping it on the 0.020 tier (fee 2985, total 27225). An earlier corner instance that claimed a tier crossing was rewritten.
- **Package suppression cascade is exercised through `POST /packages/{id}/price`**, not publish, because attaching or invalidating a leg returns the package to DRAFT and clears the money fields.
- **A second offer on the same plan needs a fresh `GET /rate-plans/{id}`** — ingestion bumps `RatePlan.version`, which is exactly the OCC corner instance.
- **The horizon-boundary corner uses an open-ended agreement** so `ERR_AGREEMENT_NOT_ACTIVE` cannot mask `ERR_TRAVEL_DATE_OUT_OF_RANGE` (2027-12-18 passes, 2027-12-19 fails).
- **Model-agreement windows are closed intervals** (touching end date is an overlap) while **placement windows are half-open**, so adjacency is legal but a shared day is not; capacity uses a strict `>` so exactly-3 slots is allowed.
- **Reverse pointers that are not true FKs omit the `FK ->` prefix** to avoid spurious reverse-reachability demands from the lint.
- **Negative instances are named with `_rejected` / `_cannot_` / `_returns_unauthenticated` / `_input_ignored` suffixes** so the lint's negative-trigger exemption waives the role-membership and payload-subset checks (e.g. `as: "MarketplaceIntern"` for the 401 case).

### Consistency fixes applied to SCAFFOLD.yaml

`CERT_EXPIRED`/`CERT_REVOKED` → `CERTIFICATION_EXPIRED`/`CERTIFICATION_REVOKED` everywhere; five transition `actor:` values that contradicted their endpoint `roles:` (agreement terminate, rate-plan archive, placement approve, both placement cancels, supplier reinstate) corrected and re-audited programmatically; `PlacementAgreement.approved_by_user_id` description repointed from ComplianceOfficer to PlatformAdmin; a stale "validations priority 22" cross-reference corrected to 25.

Forbidden concurrency vocabulary is absent from all three files (one stray "simultaneously" in the difficulty file was rewritten to "also", after which the lint was re-run clean). Every numeric literal in both design files was produced by executing the scaffold's own formulas in Python before being written.

## Step 3: Copy shared files — 2026-09-03T16:13:23.943Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T16:25:48.627Z

All three hard contracts pass. PRD written to `workspace/PRD.md`.

### Section structure (508 lines)

**§1. Introduction** — 3 paragraphs framing merchant-vs-agency model selection, the commercial/regulatory pressure pair, and the entity landscape; notes all paths mount at the service root.

**§2. Global Specifications & System-Wide Principles** (12 subsections)
- 2.1 Marketplace Actors and RBAC — headers, all 6 role names, per-role identity translation (`SupplierUser` is `entity_backed:Supplier`; the other five are opaque, with every `*_user_id` audit field named)
- 2.2 API Response Structure — emitted byte-verbatim from `section-2.2-response-structure.md` (validated)
- 2.3 Pagination and List Ordering — limit 10/1/100, offset 0, default `created_at` ASC plus all 6 domain-specific orderings
- 2.4 Resource Identity, Audit Fields and Immutable Rows — names the 3 `common_fields: false` entities (`DirectRateObservation`, `RankingEntry`, `PackageComponent`) as lacking `updated_at`/`version`
- 2.5 The Logical Clock and the Expiry Sweeps — `2026-08-01T00:00:00Z` baseline, 3 sweeps in order
- 2.6 Money, Basis Points and Rounding Discipline — the four rounding disciplines (half-up, ceiling, floor+largest-remainder, 2dp)
- 2.7 OCC — both `concurrency_rules` entries with endpoint, `expected_*_version`, `ERR_STALE_VERSION`/412, plus the explicit "no other endpoint takes a version field"
- 2.8 Nested Addressing and Path Resolution Order — all 17 404 identities
- 2.9 Segregation of Duties — all 6 comparisons
- 2.10 Validation Precedence — all 33 validations as an ordered list with `applies_to` scopes, plus 4 worked precedence consequences
- 2.11 Cascade Propagation — the 4-hop chain, both cascade heads, no-reverse and version-bump rules, `ERR_SUPPLIER_OFFBOARDED`
- 2.12 Regulated Disclosure and Total-Price Display

**§3. Business Logic & Workflows** (9 subsections, grouped by commercial lifecycle) — 3.1 Markets/Onboarding/Certification · 3.2 Merchant vs Agency Agreements · 3.3 Negotiated Overrides and the Rate Selector · 3.4 Rate Ingestion and the Sell-Price Build · 3.5 Parity Monitoring/Mediation/Holds · 3.6 Placement, Ranking Governance, Paid Disclosure · 3.7 Packages and Opaque Bundle Pricing · 3.8 Booking/Capture/Confirmation/Refund Pass-Through · 3.9 Dispute Mediation, Liability Allocation, Scorecards

**§4. Endpoint Definitions** — 4-column table, 86 rows. **§5. Error Code Catalogue** — 2-column table, 74 rows.

### Coverage

| Category | Scaffold | Documented |
|---|---|---|
| Endpoints | 86 | 86 |
| Validations | 33 | 33 (all with priority position + applies_to) |
| Errors | 74 | 74 in table; 74/74 also condition-bearing in §2/§3 prose |
| Calculations | 9 | 9 (full prose translation, no operator syntax) |
| State machines / transitions | 13 / 64 | 13 / 64 |
| Entities / field names | 17 / 168 | all |
| Concurrency rules | 2 | 2 |

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 168 required, 168 present, 0 missing
- endpoints[].request_body/input: 95 required, 95 present, 0 missing
- endpoints[].query_params: included in the above (limit/offset + filters), 0 missing
- union of required identifiers: 177 required, 177 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose (§2.10 ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 64 checked, 64 fully expressed (from/to, preconditions paired with error_id, side effects), 0 missing
- calculations[]: 9 checked, 9 fully expressed (inputs, pinned evaluation order, constants, precision, both variants where declared), 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 86 endpoints checked, all side-effect sets expressed in the owning workflow narrative, 0 missing
- entities[].fields[] structured content: 168 checked, defaults/initials/enums/computed-derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked (MERCHANT vs AGENCY pricing paths, PRELIMINARY vs BINDING liability, PROVISIONAL vs FINAL scorecard, 4 cancellation policies, 4 severity bands, CERTIFY/PROVISIONAL/REJECT, PENDING→LIVE vs SUPPRESSED→LIVE, 3 close-out origins, COMPLIANT vs WAIVED, REJECTED vs REVOKED override exits, PROPOSED→REJECTED vs ACTIVE→CANCELLED placement), 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1182
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One scaffold inconsistency worth flagging to the orchestrator: `Booking.collection_model` is constrained `enum: MERCHANT|AGENCY` on the entity, but the `POST /bookings` description says the values are `MARKETPLACE_OF_RECORD`/`SUPPLIER_OF_RECORD`. I followed the entity-level enum (`MERCHANT`/`AGENCY`), since that is the schema constraint. Also, `CERT_CONTENT_PASS` / `CERT_CONNECTIVITY_PASS` are referenced by the `IN_REVIEW → CERTIFIED` precondition but carry no numeric value anywhere in the scaffold, so the PRD states the condition as "at least the content/connectivity pass mark" without inventing a threshold.

**Orchestrator truncation check (per invocation instruction):** `wc -l` = 508 lines / 111539 bytes. `tail -25` ends inside the §5 Error Code Catalogue table on a complete row (`| ERR_NOTHING_TO_DISPUTE | 422 |`) — §5 is the final section, so this is a real section boundary, not a mid-sentence cut. Programmatic re-count confirms 86 endpoint rows in §4 and 74 error rows in §5, matching the scaffold. NOT truncated; no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-03T17:10:19.613Z

Test generation for `task_2581_online_travel_agency_model_rate_parity_administration` is complete.

### Output location (path rule satisfied)

Both directories are at the **task root**. `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — `find workspace -iname "*test*" -o -iname conftest.py` returns nothing. Stray `__pycache__` dirs from the collect check were removed.

### Files written (line counts)

`test_helpers/` — 2 084 lines total
- `__init__.py` 26 (registers `ERROR_HTTP_STATUS` via `set_error_http_status_map`)
- `types.py` 49, `constants.py` 125, `api_errors.py` 171 (all 74 PRD §5 ids + status map)
- `api_client.py` 518 (one method per endpoint), `assertions.py` 169, `test_users.py` 64
- `factories.py` 271 (`_OMIT` sentinel payload builders), `fixtures.py` 691 (`Builder` + composite scenarios `certified_hotel`, `hotel_agency_offer`, `air_merchant_offer`, `two_leg_package`, `captured_booking`, `parity_case_at`)

`test_suite/` — 3 308 lines total, **87 tests**
- `conftest.py` 39
- `test_01_markets_suppliers_and_certification.py` 415 — 10 tests
- `test_02_model_agreements_and_overrides.py` 300 — 7
- `test_03_rate_plans_and_offer_pricing.py` 486 — 15
- `test_04_parity_monitoring.py` 303 — 8
- `test_05_placement_and_ranking.py` 361 — 9
- `test_06_packages.py` 395 — 11
- `test_07_bookings_and_refunds.py` 499 — 15
- `test_08_disputes_and_scorecards.py` 510 — 12

### Coverage against the two design indices

- **Queue A (difficulty): 38 tests / 19 instances — exactly 2 per instance, 100% covered.** All ten rule families: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check` (3 instances), `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.
- **Queue B (corner): 49 tests / 49 non-stub instances — every non-stub instance covered, ≥1 test each.**
- **17 `excluded_because:` stubs were not translated** (4 `state_machines`, 8 `calculations`, 4 `validations`, 2 `cross_cutting_layers` — e.g. `refund_reversal_compensates_the_original_refund_side_effects`, `composite_score_weight_accumulation`, `state_priority_beats_fiscal_priority_on_booking`), as required.
- **SKIPPED instances: none.** Every non-stub instance passed the PRD-first two-condition filter, so no gaps had to be left. Where the design and the PRD disagreed, the PRD won and the test asserts PRD behaviour: `collection_model` is `AGENCY`/`MERCHANT` (design said `SUPPLIER_OF_RECORD`), new offers start `PENDING` (design said `PENDING_REVIEW`), `EXCL_TAXES` → `TOTAL_UPFRONT`. The one design instance with no PRD prose behind it (`consistency_model`) was re-grounded on PRD 2.11 ("each hop must be applied in full") plus PRD 3.7 (`priced_at` stamped), which uniquely derives the asserted outcome.

### Audit passes run

1. **PRD-citation pass**: 138 quoted fragments extracted from all 87 docstrings and matched verbatim against `workspace/PRD.md` (whitespace/arrow-glyph normalised, ellipsis-split). Final result: **0 missing**. This pass caught and fixed 29 paraphrases, including an invented `A missing RatePlan is ERR_RATE_PLAN_NOT_FOUND`, a wrong travel-date-horizon sentence, a fabricated "Publishing an offer moves it from PENDING to LIVE", a non-existent "every accepted mutation increments version by exactly one", a wrong mediation-fee wording ("2500 cents of base fee" vs the PRD's "a flat base of 2,500 cents"), stripped `§` markers, and bracketed verb edits (`increment[s]`, `stamp[s]`) replaced by the PRD's own gerunds.
2. **Section-citation pass**: each `PRD X.Y:` label checked against the actual section span containing its quote. **0 bad** after fixing three mis-citations (`parity_monitored` default is §3.4 not §3.1; `ranking_disclosure_required` default is §2.12; component-suppression de-pricing is §3.4 not §3.6) and re-citing stale-version guards to §2.7, the provisional-expiry chain to §3.1 + §2.5, and supplier scoping to §2.1.
3. **Design-citation pass**: every test has exactly one `Design:` line, it is the last docstring line, the tag resolves to a real instance in the named queue **and** the correct section/rule_id, and no tag points at a stub. **0 problems** after fixing one section mismatch (`offer_create_with_a_stale_expected_rate_plan_version_is_rejected` lives in `cross_cutting_layers`, not `errors`).
4. **Static checks**: `pyflakes` clean across all 17 files; `pytest --collect-only` collects **87 tests in 0.49 s** with no import errors. No occurrence of "scaffold", no `skip`/`xfail` anywhere; decimals compared with `pytest.approx(..., abs=0.01)` (percentages `abs=0.0001`).

### Notable content

Arithmetic was independently re-derived from PRD prose before being asserted: agency offer build 24000 → 3600/240/24240/20400 and its half-cent neighbours (24001, 24050); merchant gross-up by ceiling (119936/0.88 → 136291, 80000/0.80 → 100000); parity breach 58/100/306/821 bps for direct 24100/24000/23520/22400 with band edges inclusive-below; package tiers 6%/9% with floor-then-largest-remainder allocation and the exact 300000 threshold (27000 discount, allocs 18000/9000); refund ledger at the cutoff (1.00 → 24240, ledger 3600/20400/240) and one hour inside it (0.50 → 12120, tax as residual 120); mediation fees 2520/2742/2985/6000/9430; settlement 207437 splitting 51859/155578 preliminarily against the filing agreement versus a fraud-capped 50000 bindingly; ranking organic 89.50 with boosts to 95.50/97.50; scorecard provisional 85.60 (penalty 4, parity 68, 2 cases) versus final 92.80 (penalty 1, parity 92, 1 case) under weights 0.30/0.25/0.20/0.25.

Priority-pair tests cite real §2.10 ladder positions (e.g. "9. State precondition" before "31. Quoted price agreement on booking creation"; "4. Path existence" before "6. Request shape") and assert both orderings — the higher-priority error first, then the lower-priority one once the higher condition is cleared.

Two pre-existing helper touch-ups were needed and made: five `*_USER_ID` constants added to `test_helpers/test_users.py` so audit-trail fields can be asserted, and an `air_markup_pct` parameter threaded through `two_leg_package(...)` for the 0.20-markup threshold scenario.

## Step 6: Generate Implementation — 2026-09-03T17:10:19.613Z

Implementation complete. All 15 route modules, `app.py`, and the shared core are on disk; the server boots clean and was smoke-tested end-to-end.

### Files written (line counts)

**Core:** `store.py` 91, `clock.py` 88, `errors.py` 101, `response.py` 61, `auth.py` 69, `validate.py` 204, `calc.py` 500, `cascade.py` 168, `requirements.txt` (`Flask==3.0.3`), `start.sh` (guarded pip install + `exec python3 app.py`, `PORT` default 10000, binds `0.0.0.0`).

**Routes:** `app.py` 58, `routes/system.py` 45, `routes/markets.py` 60, `routes/suppliers.py` 108, `routes/agreements.py` 160, `routes/certifications.py` 171, `routes/rate_plans.py` 111, `routes/offers.py` 146, `routes/parity.py` 232, `routes/overrides.py` 140, `routes/placements.py` 114, `routes/ranking.py` 171, `routes/packages.py` 221, `routes/bookings.py` 256, `routes/disputes.py` 187, `routes/scorecards.py` 76, plus `routes/__init__.py` 41 and `routes/common.py` 117. Total 3,696 lines.

### Coverage (machine-verified)

- **86 endpoints** — counted off the live Flask `url_map` (excluding `/healthz`): exactly 86, matching SCAFFOLD §1.5.
- **74 errors** — script-diffed the SCAFFOLD catalog against `errors.ERROR_HTTP`: 0 missing, 0 status mismatches, 0 impl-only extras. All 74 are reachable (57 raised literally, the 17 `*_NOT_FOUND` via `common.find`'s table).
- **17 entities** — 17 collections in `store.COLLECTIONS`; the three append-only rows (DirectRateObservation, RankingEntry, PackageComponent) are created with `versioned=False` so they carry only `id`/`created_at`.
- **33 validations** — enforced first-failure-wins in ascending priority inside each handler; the ordering traps are honoured: body-FK existence (5) before shape (6); OCC (8) before state (9), component mix (21) and liveness (26); state (9) before SoD (10); disclosure (12/11) before mix; booking target exclusivity (23) before price (31) before allotment (32); SoD (10) before capacity (15).
- **9 calculations** in `calc.py` with the pinned rounding — merchant ceiling gross-up, half-up taxes/margins, floor bundle discount with largest-remainder allocation tie-broken on offer `created_at`, integer-bps parity bands, 2dp scores, tiered mediation fee keyed on `refund_due_cents`, residual (never re-rounded) tax refund share.
- **13 state machines** across the route modules plus the four-hop cascades and the three forward-only clock sweeps in `cascade.py`.
- Storage is pure in-memory dicts, empty at boot, zero seeding.

### Smoke test

Ran on `PORT=9828` via `bash start.sh`; two scripted flows (~70 calls). All green: market→supplier→MERCHANT agreement→certification (net 80000 @ 0.2 markup → gross 100000, taxes 10000, display 110000, margin 20000, payable 80000); stale token → `ERR_STALE_VERSION` 412; parity 1000 bps SEVERE → notify → escalate → `PARITY_HOLD`/`SUPPRESSED` → close COMPLIANT → release → republish; booking capture→confirm→cancel FLEX 100% → `REFUNDED_FULL`/`CANCELLED` with conserved identity verified; ranking boost cap + `ERR_DISCLOSURE_MISSING`; packages 176250 → 6% tier → floor discount 10575 → allocations 3150/7425, both invariants True, `ERR_OPAQUE_DISCLOSURE_FORBIDDEN`; disputes FRAUD 300000 capped to 165675 → 3.5% fee 8299 → settlement 173974 → preliminary 86987/86987 → binding capped 50000/123974, SoD blocks both self-approves; cascade withdrawals in one hop set; clock sweeps + `ERR_PERIOD_NOT_CLOSED`; auth/pagination edges.

Server was stopped by its exact PID (3606740, the sole listener on 9828) — no pattern kill was used; port confirmed closed afterwards.

### Judgement calls where the spec is silent (PRD given precedence over SCAFFOLD)

- `collection_model` values are `MERCHANT`/`AGENCY` per PRD §3.8 and the entity enum, not the SCAFFOLD prose's `MARKETPLACE_OF_RECORD`/`SUPPLIER_OF_RECORD`.
- Package booking money split: taxes and supplier payable are summed from the component offers and the marketplace margin absorbs the bundle discount, which is the only split that keeps PRD §3.8's conserved identity exact.
- Certification pass marks have no declared threshold or error, so scores never block a CERTIFY decision.
- Undeclared preconditions reuse the nearest catalog id: offboard blocked by live bookings → `ERR_BOOKING_NOT_RESERVED`; close-out with held allotment → `ERR_OFFER_NOT_LIVE`; archive of a non-ACTIVE plan → `ERR_RATE_PLAN_NOT_ON_HOLD`; placement approve on a non-ACTIVE supplier → `ERR_SUPPLIER_NOT_CERTIFIED`; override approve with no covering ACTIVE agreement → `ERR_AGREEMENT_NOT_ACTIVE`; notify/respond from a wrong non-terminal parity state → `ERR_PARITY_CASE_NOT_NOTIFIED`; escalate on a MINOR case → `ERR_PARITY_CASE_NOT_ESCALATABLE`; REVERSE_REFUND with nothing refunded → `ERR_PAYMENT_NOT_CAPTURED`.
- Override `value` is validated only as `>= 0` (the declared constraint); no undeclared 0.5 ceiling was imposed.
- On `PRICED → DRAFT` invalidation the component snapshots are cleared along with the alloc fields, following the SCAFFOLD state-machine side effect over the endpoint table's attach wording.

**Orchestrator verification:** `test_helpers/` (9 files) and `test_suite/` (9 files) are at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. No move needed.

## Step 7: Run Tests and Iterate — 2026-09-03T17:25:00.000Z

Clean sweep achieved. Summary below.

### Iterations run
2 (one diagnostic sweep, one fix, one confirming sweep).

### Diagnosis
Sweep 1 was identical across all 8 rounds: **11 passed / 87 total, 76 failed** — fully deterministic, no flakiness. Aggregating the failure detail from all 8 `results.$i.json` collapsed to **a single distinct error message** across all 76 failures:

```
AssertionError: Expected 201, got 400: {"data":{"error_id":"ERR_INVALID_REQUEST",
"message":"market_code must be 3-12 uppercase letters or hyphens."}...
```

Every failure aborted in setup at `test_helpers/fixtures.py:57` (`Builder.market()`), i.e. the classic single-upstream-fixture-bug-masquerading-as-many signature. (Note: `grep FAILED` on the interleaved `sweep.log` is unreliable here — 8 concurrent pytest writers splice each other's live-progress lines, producing phantom names like `test_rate_plan_read_with_an_unknown_id_is_not_found FAILED` for a test the results JSON records as `passed`. The results files are the only trustworthy source.)

**STEP 1 (coverage + unique derivability): PRD verbatim-covers, and uniquely.** PRD §3.1: *"A `PlatformAdmin` registers one with a `market_code` — 3 to 12 characters of uppercase letters and hyphens, unique across all markets…"*. Letters-and-hyphens is stated as the full character set; a digit-bearing code is not admissible under any faithful reading. The implementation's `CODE_RE = re.compile(r"^[A-Z-]{3,12}$")` in `routes/markets.py:17` matches the PRD sentence exactly.

**STEP 2 (test-vs-PRD consistency): TEST IS WRONG.** The fixture layer issued a request the PRD-faithful implementation correctly rejects — `test_helpers/factories.py` `market_payload()` generated `market_code` as `f"EU-M{n:03d}"` from a session counter, producing `EU-M001`, `EU-M002`, … with digits. This is exactly the case the protocol reserves for a `test_helpers/` fix, not an implementation relaxation. Dropping the digit restriction from `markets.py` would have been the forbidden move (weakening a PRD-required check to accommodate a non-conforming fixture).

### Tests deleted
**None.** No test asserted a scaffold-only or PRD-silent rule; the one defect was in the fixture layer.

### Fixes applied to `test_helpers/`
- `test_helpers/factories.py` — added `_alpha(n)` (base-26 uppercase-letter encoding of the counter) and changed `market_payload()`'s generated `market_code` from `f"EU-M{n:03d}"` to `f"EU-M{_alpha(n)}"`, so auto-generated codes stay unique per test while honouring PRD §3.1's uppercase-letters-and-hyphens character set and 3–12 length. Wide reach by design: this single fixture backs 76 of the 87 tests. Codes remain 5 chars (`EU-MA`, `EU-MB`, …), well inside the bound.

### Fixes applied to `implementation/`
**None.** The implementation was already PRD-faithful on this rule; no endpoint, field, side effect, or check was added, removed, or weakened.

### Final sweep evidence (verbatim per-round passed/total)

All 8 files present on disk from the same final sweep, written `Sep 3 17:22`:

```
results.1.json  87 / 87
results.2.json  87 / 87
results.3.json  87 / 87
results.4.json  87 / 87
results.5.json  87 / 87
results.6.json  87 / 87
results.7.json  87 / 87
results.8.json  87 / 87
```

Zero failing tests in the union across all 8 rounds — no flakiness surfaced. Servers were only ever stopped by exact PID on the probe port (17581, confirmed free afterwards); no pattern kill was used.

**Orchestrator independent re-verification** (per the known failure mode where a Step 7 agent claims a clean sweep with no artifacts behind it): `ls -la results.*.json` shows all 8 files ~27 KB each, mtime `Sep 3 17:22`, and a direct JSON parse confirms `passed=87 total=87 failed=0` for every one. Evidence stands.

**Step 8 skip-condition adjudication:** Step 7 reports 0 deletions, 0 `test_suite/` fixes, 0 `implementation/` fixes, but **1** `test_helpers/` fix. The skip condition requires all four counts to be zero, so it is NOT met and Step 8 runs. The single diff item is a pure fixture bug (a generated `market_code` violating a rule PRD already states verbatim), so Step 8 may legitimately conclude there is nothing to patch and emit a byte-identical `PRD_FINALIZED.md` — that is the correct outcome for a fixture-only diff, not a failure to run.

## Step 8: Finalize PRD — 2026-09-03T17:28:00.000Z

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md`. **Zero edits** — the sole Step 7 diff item was a pure test-fixture bug on a rule the PRD already states verbatim and the implementation already matches on every dimension.

### Line counts
- `PRD.md`: 508 lines; `PRD_FINALIZED.md`: 508 lines; delta **0 lines (0.0%)**. md5 identical (`09a38ceb26babd5ba45b8dce82780799`).

### Changes
None.

### Verification of the market_code site (the mandated check)

Subject: the `market_code` rule on `POST /markets`. PRD §3.1 line 172 vs `implementation/routes/markets.py:17-42`.

Paths enumerated and read/grepped: `implementation/routes/markets.py` (all three endpoints — create, read, list), `implementation/validate.py` (`str_req`, `int_req`, `enum_req`, `bool_opt`), `implementation/errors.py` (full `ERROR_HTTP` map), `grep -rn "market_code"` across `implementation/`, `test_helpers/`, `test_suite/`, plus PRD §2.10 (check-ordering list, items 6 and 22), §2.12 (disclosure default), §5 (error/status table).

Dimension-by-dimension result:

| Dimension | PRD §3.1 / §2.x | Implementation | Verdict |
|---|---|---|---|
| Character set | "uppercase letters and hyphens" | `[A-Z-]` | matches; no digits admissible under any reading |
| Length bounds | "3 to 12 characters" | `{3,12}` — inclusive at both 3 and 12 | matches; "3 to 12 characters" is inclusive-range phrasing, not genuinely open |
| Uniqueness scope | "unique across all markets" | iterates every row of `db["markets"]`, no status filter — a `CLOSED` market still blocks reuse | matches ("all markets" covers `CLOSED`) |
| Duplicate error | `ERR_MARKET_CODE_TAKEN`; §2.10 item 22 and §5 give 409 | `ApiError("ERR_MARKET_CODE_TAKEN")` → 409 via `ERROR_HTTP` | matches |
| Malformed code error | §2.10 item 6 / §5: `ERR_INVALID_REQUEST` (400) | `ApiError("ERR_INVALID_REQUEST", …)` → 400 | matches |
| Check ordering | §2.10: shape (6) before uniqueness (22) | all `validate.*` calls precede the uniqueness loop | matches |
| Normalization | PRD implies stored verbatim | no trim/upcase; stored as supplied | matches |
| `ranking_disclosure_required` default | §2.12: "true … the default when the flag is omitted at registration" | `bool_opt(..., True)` | already pinned in PRD |

Nothing at that site was left open by the PRD, so there was nothing to patch. Corroborating evidence that the defect was fixture-only: `test_helpers/factories.py:39-58` now encodes the counter as base-26 letters (`EU-MA`, `EU-MB`, …) replacing the digit-bearing `EU-M{n:03d}`, and `test_suite/test_01_markets_suppliers_and_certification.py:189-224` still asserts the full PRD rule (409 / `ERR_MARKET_CODE_TAKEN` on duplicate) unweakened — no assertion was relaxed, and no implementation check was touched.

**Orchestrator decision for Step 9:** because `PRD_FINALIZED.md` is byte-identical to `PRD.md`, a single-agent Step 9 has no partial-edit signal to distinguish "scanned and found nothing" from "never actually scanned" — and a known failure mode is a Step 9 agent that emits an identical copy without walking the implementation. The implementation is 3,696 lines across 18 modules, which is also more than one agent can exhaustively cross-reference against a 508-line PRD in one pass. Step 9 is therefore run as **three sequential file-partitioned passes**, each appending to the same `PRD_COMPLETED.md`: (A) core/global semantics — `app.py`, `store.py`, `clock.py`, `errors.py`, `response.py`, `auth.py`, `validate.py`, `cascade.py`, `routes/__init__.py`, `routes/common.py`, `routes/system.py`; (B) commercial-setup routes — `markets.py`, `suppliers.py`, `agreements.py`, `certifications.py`, `rate_plans.py`, `offers.py`, `overrides.py` plus the offer-pricing half of `calc.py`; (C) operations routes — `parity.py`, `placements.py`, `ranking.py`, `packages.py`, `bookings.py`, `disputes.py`, `scorecards.py` plus the remaining `calc.py` formulas. Passes are strictly sequential to avoid concurrent writes to the same file.

## Step 9: Complete PRD — 2026-09-03T18:00:00.000Z

Run as three sequential file-partitioned passes over a shared `PRD_COMPLETED.md` (rationale recorded at the end of the Step 8 entry). Net result: **508 → 513 lines, 111,539 → 137,270 chars (+25,731, +23.1%)**, **79 changes: 57 ambiguity-pins, 22 mismatch-revisions.**

### Pass A — core / cross-cutting semantics (`app.py`, `store.py`, `clock.py`, `errors.py`, `response.py`, `auth.py`, `validate.py`, `cascade.py`, `routes/__init__.py`, `routes/common.py`, `routes/system.py`)

`PRD_FINALIZED.md` 508 lines / 111,539 chars → 513 lines / 122,347 chars (**+5 lines, +10,808 chars**). 22 edits: **18 ambiguity-pins, 4 mismatch-revisions**. No sections added; one new paragraph (§2.8) and 3 rows appended to the §5 table; everything else in-paragraph. Verified live against a running instance on port 17331 (unknown path, wrong method, trailing slash, no-auth, malformed JSON, array body, no body, wrong-case role, empty header, empty/padded pagination params), then shut down by port pid.

- §1 Introduction — insert — ambiguity — state is process-local and every boot starts empty; nothing seeded — app.py:19-20, store.py:27-35
- §2.1 ¶1 — insert — ambiguity — present-but-empty header counts as absent; role compared exactly/case-sensitively; `X-User-ID` not resolved at auth time, so a `SupplierUser` naming no supplier authenticates and only fails scope on writes — auth.py:32-38
- §2.1 ¶3 — insert — ambiguity — a booking spanning two suppliers admits a `SupplierUser` matching **any** component supplier (confirm, complete, file-dispute); undeterminable owner → same 403 — auth.py:45,52-60 + routes/common.py:106-112
- §2.2 `api_request_id` bullet — revise — ambiguity — `req_` + exactly 20 chars from A–Z/0–9 — response.py:10-14
- §2.2 `api_request_timestamp` bullet — revise — **mismatch** — read from the host wall clock, not the logical clock, and must not be used as a domain timestamp — response.py:17-19
- §2.2 pagination bullet — insert — ambiguity — pagination keys appear **only** on list `meta`; object/empty/error `meta` carries just the two keys; `response_type` `"array"` even for an empty page — response.py:29-52
- §2.3 ¶1 — insert — ambiguity — `offset` has no upper bound and may exceed `total_count`; empty-string `limit`/`offset` = omitted; only plain decimal integer spelling accepted (`10.5`, `010`, `+5` rejected, surrounding whitespace tolerated); undeclared query params ignored — validate.py:147-167
- §2.3 ¶2 — insert — ambiguity — every ordering carries an implicit insertion-order tie-break, reversed wholesale under the two DESC orderings; filter semantics (exact equality, empty=absent, enum/bool/date rejection forms, id filters never existence-checked → empty page) — store.py:88-91, routes/common.py:40-45, validate.py:170-204
- §2.4 ¶1 — insert — ambiguity — `created_at` comes from the logical clock; two internal fields (insertion sequence, supplier's backing-certification pointer) are never serialised — store.py:50,68-71
- §2.5 ¶1 — revise — **mismatch** — wall-clock exception named; `current_utc` parse rules (`Z`, numeric offset, naive read as UTC, normalised before the forward comparison); clock-set returns empty `data`; only `created_at`/`updated_at` guarantee 3 fractional digits — every other server-stamped instant omits the fraction when milliseconds are zero — clock.py:29-66, routes/system.py:16-26
- §2.5 ¶2 first sentence — revise — **mismatch** — clock advances before the sweeps so touched rows carry the new instant; sweeps visit rows in insertion order; `expires_at` must be non-null; suspension fires only for the backing package and only for an `ACTIVE` supplier, otherwise the cert expires silently — cascade.py:140-158
- §2.5 ¶2 last sentence — insert — ambiguity — setting the clock to the instant it already holds runs no sweep (strictly-later only); date-based sweeps compare calendar dates — routes/system.py:24, cascade.py:161,166
- §2.8 (new paragraph) — insert — ambiguity — routing precedes the ladder: unmatched path → `ERR_NOT_FOUND` 404 with no auth check, wrong method → `ERR_METHOD_NOT_ALLOWED` 405, fault → `ERR_INTERNAL` 500, all in the standard error envelope; trailing slash insignificant — app.py:18,27-45
- §2.9 — insert — ambiguity — exact string match; a null stored proposer/opener/filer can never match, so the operation proceeds — auth.py:63-69
- §2.10 item 3 — insert — **mismatch** — scope outranks path existence only when the path id *is* the supplier; every other scoped write resolves the path row first, so 404 precedes 403 — routes/rate_plans.py:24-25, routes/certifications.py:30-31 vs routes/offers.py:33-34, routes/parity.py:169-171, routes/disputes.py:34-35, routes/bookings.py:176-177
- §2.10 item 5 — insert — ambiguity — body-reference resolution engages only for a non-empty string; absent/null/empty/other-typed references fall through to shape as 400 — routes/suppliers.py:26-27
- §2.10 item 6 — insert — ambiguity — the whole generic shape contract: unparseable/absent body = empty object (so missing-field error, not parse error), non-object body rejected, explicit `null` == absent, required strings non-empty vs optional strings type-checked only, integer fields reject bool and float-typed values, number fields accept int or float but reject bool, inclusive bounds, 10-char `YYYY-MM-DD` dates, ISO instants, exact case-sensitive enums, unknown body keys ignored — validate.py:15-144
- §2.10 item 7 — insert — ambiguity — malformed filters and malformed pagination are indistinguishable (same id/status) — validate.py:170-204
- §2.11 ¶1 — insert — ambiguity — a cascade-withdrawn ranking run also records `COMPONENT_SUPPRESSED`; hop 4's exact cleared field list; a package/run reached twice is touched once so `version` advances by exactly 1; `DRAFT` packages untouched — cascade.py:36-91, routes/packages.py:132-135
- §2.11 ¶2 — insert — ambiguity — the offboarding close-out is not a suppression: offers go straight to `CLOSED` and no dependent package or run is withdrawn/de-priced — cascade.py:120-132
- §4 preamble — insert — ambiguity — clock endpoint returns empty `data`; chargeback resolves `booking_id` at priority 5, validates but does not persist `reason_code`, requires `CAPTURED` else `ERR_PAYMENT_NOT_CAPTURED`, leaves fulfilment alone, `version` +1; `GET /healthz` is an unauthenticated liveness probe outside the envelope — routes/system.py:16-45, app.py:47-49
- §5 table — insert — ambiguity — added `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — app.py:27-45

Pass A also programmatically verified the §5 table byte-exact against `errors.ERROR_HTTP` (no missing/extra id, no status disagreement) and `routes/common.NOT_FOUND` against §2.8's 404-identity catalogue.

### Pass B — commercial-setup routes (`markets`, `suppliers`, `agreements`, `certifications`, `rate_plans`, `offers`, `overrides` + offer-pricing `calc.py`)

513 lines / 122,347 chars → 513 lines / 129,027 chars (**+6,680 chars**, no line delta). 24 changes: **16 ambiguity-pins, 8 mismatch-revisions**, all in-paragraph plus 4 one-cell §4 table row revisions.

- §2.10 item 28 — revise — mismatch — coverage check also fires on commission-override approval — overrides.py:113-117
- §2.11 — revise — mismatch — `ERR_SUPPLIER_OFFBOARDED` guard entity list completed (adds model agreements, overrides, parity cases, placement propose/approve; names booking/package/ranking/dispute/scorecard/placement-cancel as unguarded), plus its fixed ladder position: after shape+concurrency and before priority 9 on supplier/plan/offer/override/placement/parity writes, after priority 9 on agreement and certification writes — common.py:52, agreements.py:100-102, certifications.py:103-105, suppliers.py:82-85
- §3.1 markets — insert — ambiguity — no endpoint ever moves a market out of `ACTIVE`; `CLOSED` stays an accepted-but-unmatchable filter value — markets.py:19,43
- §3.1 certification submission — insert — ambiguity — a supplier may hold any number of packages concurrently — certifications.py:27-51
- §3.1 adjudication — revise — mismatch — both pass marks are zero, so no adjudicated score ever blocks `CERTIFY` — certifications.py:23-24,110
- §3.1 adjudication — revise — mismatch — the `PENDING_CERT → ACTIVE` move is conditional (a `SUSPENDED` or already-`ACTIVE` supplier keeps its status, still gets scores/level refreshed and the backing pointer repointed, and must be reinstated separately) — certifications.py:121-128
- §3.1 remediation — insert — ambiguity — prior `content_score`, `connectivity_score` and `REJECT` decision persist through remediation — certifications.py:147-151
- §3.1 revocation — insert — ambiguity — wrong-status revoke reuses `ERR_CERT_NOT_DECIDED` — certifications.py:162-163
- §3.1 revocation — insert — ambiguity — a non-`ACTIVE` supplier is untouched while the package still reaches `REVOKED` — cascade.py:96-97, certifications.py:169-170
- §3.1 offboarding — revise — mismatch — no origin-status precondition (`PENDING_CERT` is a valid origin); `reason` validated but never persisted; blocking live booking → `ERR_BOOKING_NOT_RESERVED` (409) over all component legs — suppliers.py:96-107
- §3.2 agreement window — insert — ambiguity — `effective_to` < `effective_from` → `ERR_INVALID_REQUEST`; equal dates accepted — agreements.py:47-48
- §3.3 override proposal — insert — ambiguity — `supplier_id` resolved before `rate_plan_id`; plan need not belong to the supplier — overrides.py:25-30
- §3.3 override proposal — insert — ambiguity — `value` has no ceiling on any type (may exceed §3.2's 0.5) and is number-typed even for `FLAT_FEE_CENTS`, truncated toward zero when spent; `effective_from`/`effective_to` never compared — overrides.py:34-36, calc.py:185,192
- §3.3 approval — insert — ambiguity — no covering `ACTIVE` agreement → `ERR_AGREEMENT_NOT_ACTIVE` (422); only `effective_from` is tested — overrides.py:113-117
- §3.3 approval repricing — insert — ambiguity — insertion order; plan status irrelevant; an offer with no covering `ACTIVE` agreement is skipped silently and approval still succeeds; selector re-runs wholesale and the write is unconditional so `version` advances even when figures are unchanged — overrides.py:83-100
- §3.3 selector — insert — ambiguity — equal `created_at` broken by insertion order (earlier-written wins) — calc.py:159-163
- §3.4 rate plan — revise — mismatch — `currency` validated only as a required non-empty string, never against a code list — rate_plans.py:32
- §3.4 archival — revise — ambiguity — non-`ACTIVE` plan → `ERR_RATE_PLAN_NOT_ON_HOLD`; `LIVE` offers → `ERR_OFFER_NOT_LIVE` checked second; `SUPPRESSED`/`CLOSED`/`SUPERSEDED` offers untouched — rate_plans.py:100-110
- §3.4 step three — insert — ambiguity — a flat fee is unclamped, so an agency fee above `net_rate_cents` leaves `supplier_payable_cents` negative — calc.py:191-204
- §3.4 close-out — insert — ambiguity — already `CLOSED`/`SUPERSEDED` **and** held allotment both report `ERR_OFFER_NOT_LIVE` — offers.py:139-143
- §4 `GET /markets` — revise — ambiguity — declares the `status` filter — markets.py:57
- §4 `GET /suppliers` — revise — mismatch — adds the `certification_level` filter — suppliers.py:63
- §4 `GET /certifications` — revise — mismatch — adds the `decision` filter — certifications.py:65
- §4 `GET /commission-overrides` — revise — mismatch — adds the `override_type` filter — overrides.py:68

### Pass C — operations routes (`parity`, `placements`, `ranking`, `packages`, `bookings`, `disputes`, `scorecards` + remaining `calc.py`)

513 lines / 129,027 chars → 513 lines / 137,270 chars (**+8,243 chars**, no line delta). 33 substantive changes: **23 ambiguity-pins, 10 mismatch-revisions**.

- §3.5 — insert — ambiguity — observation posting never examines the plan's `status` (ACTIVE / PARITY_HOLD / ARCHIVED all accepted) — parity.py:43-49
- §3.5 — insert — ambiguity — two `LIVE` offers can coexist for a plan+date; the latest `created_at`, insertion-order-last, is the compared offer — calc.py:223-232
- §3.5 — insert — ambiguity — notifying from any origin other than `OPEN`/`SUPPLIER_RESPONDED` reuses `ERR_PARITY_CASE_NOT_NOTIFIED`, and that state test precedes the round cap — parity.py:155-159
- §3.5 — insert — ambiguity — the `MAJOR`/`SEVERE` severity condition reuses `ERR_PARITY_CASE_NOT_ESCALATABLE`, evaluated after the status condition — parity.py:195-199
- §3.5 — insert — ambiguity — escalation's hold hop is conditional on the plan being `ACTIVE`; otherwise the case still escalates and `parity_strikes` still increments, but no plan/offer is touched — parity.py:200-205, cascade.py:109-117
- §3.5 — insert — ambiguity — `WAIVED` asked for by a non-`ComplianceOfficer` → `ERR_UNAUTHORIZED`, tested ahead of the terminal/state conditions — parity.py:217-219
- §3.6 — insert — ambiguity — placement body refs resolve supplier-then-market; `window_start`/`window_end` are never compared, so an inverted pair is accepted and passes capacity vacuously — placements.py:24-37, calc.py:483-500
- §3.6 — insert — ambiguity — the `visibility_status` `ACTIVE` requirement on approval reports `ERR_SUPPLIER_NOT_CERTIFIED` (422) — placements.py:91-93
- §2.10 item 13 — revise — mismatch — widened from offer publication only to also cover placement approval (kept above capacity at 15) — placements.py:91
- §3.6 — revise — mismatch — `disclosure_version` must be present **and non-empty**; the empty string §2.10's optional-string rule admits still fails `ERR_DISCLOSURE_MISSING` — ranking.py:117-119
- §3.6 — insert — ambiguity — `sort_profile` is recorded for disclosure only and never affects scoring or ordering — ranking.py:59-63, calc.py:473
- §3.7 — insert — ambiguity — `opaque` is a required boolean with no default — packages.py:53-55
- §3.7 — revise — mismatch — `PRICED → DRAFT` invalidation also nulls every component's `display_total_snapshot_cents`, including the just-attached leg — packages.py:134-137, cascade.py:36-46
- §3.8 — insert — ambiguity — booking body refs resolve offer-then-package; a package sale never re-checks its component offers' statuses (only `PUBLISHED` + allotment) — bookings.py:48-51, 61-64
- §3.8 — insert — ambiguity — package money split: taxes and supplier payable summed live from the component offers, margin as the residual absorbing the bundle discount; `collection_model` (only `MERCHANT`/`AGENCY`) read from the governing leg = first `HOTEL` component in attachment order, else first component — bookings.py:21-39, 82-95, 114
- §3.8 — revise — ambiguity — capture tests `fulfillment_status` first (`ERR_BOOKING_ALREADY_CANCELLED`), then `AUTHORIZED` — bookings.py:164-167
- §3.8 — insert — ambiguity — confirm's `AUTHORIZED`-or-`CAPTURED` condition reports `ERR_PAYMENT_NOT_AUTHORIZED` — bookings.py:182-183
- §3.8 — insert — ambiguity — complete's payment condition reports `ERR_PAYMENT_NOT_CAPTURED`, tested after the `CONFIRMED` and arrival conditions — bookings.py:246-253
- §3.8 — revise — mismatch — the chargeback bar on cancellation attaches only to the `CONFIRMED` origin; a `RESERVED` booking in chargeback cancels normally — bookings.py:201-204
- §3.8 — insert — ambiguity — `cancellation_refund_pct` stored as `1` / `0.5` / `0` — bookings.py:216, calc.py:86-91
- §3.9 — insert — ambiguity — the binding agreement's "booked travel date" is the package's own `travel_date` for a package sale — disputes.py:22-28
- §3.9 — insert — ambiguity — no filing agreement → marketplace share 0, supplier carries the whole total — calc.py:328-331
- §3.9 — insert — ambiguity — no binding agreement → `FRAUD` left uncapped and `SPLIT`'s effective share is 0% — calc.py:334-348
- §3.9 — insert — ambiguity — `REVERSE_REFUND` with nothing refunded → `ERR_PAYMENT_NOT_CAPTURED`, evaluated last (after state and SoD) — disputes.py:158-166
- §3.9 — insert — ambiguity — a dispute's `supplier_id` is the governing (`HOTEL`) leg's supplier even though any leg's `SupplierUser` may file — disputes.py:45-47, common.py:86-117
- §3.9 — insert — ambiguity — scorecard `period_start`/`period_end` are never compared and are unconstrained relative to the clock — scorecards.py:25-26
- §3.9 — revise — mismatch — finalisation also overwrites `content_component` and `connectivity_component`, re-read from the supplier at finalisation — scorecards.py:71-73, calc.py:383-385
- §2.6 — insert — ambiguity — JSON rendering: the three ranking scores and every stored rate/fraction emit a whole value as a plain integer (`100`, `0`), while `composite_score` alone keeps its fractional part (`100.0`) — calc.py:69-71, 86-91
- §4 (5 rows) — revise — mismatch — undeclared-but-implemented list filters added, since §2.3 would otherwise have them ignored: `/parity-cases` `severity`, `/packages` `opaque`, `/package-components` `component_type`, `/dispute-cases` `status`, `/ranking-entries` `is_paid_placement` — parity.py:132, packages.py:91,211, disputes.py:97, ranking.py:159

### Pass C final structural check (all pass)

`wc -l` = 513; `wc -c` = 137,270; headings §1 → §2 (2.1–2.12) → §3 (3.1–3.9) → §4 → §5 all present and in order; §4 endpoint table 86 rows; §5 error table 77 rows (74 original + 3 routing-level ids from pass A); tail ends on the real §5 boundary (`| ERR_NOTHING_TO_DISPUTE | 422 |`), no mid-sentence cut; no prose injected inside either table.

### Orchestrator verification

`md5sum` confirms `PRD_COMPLETED.md` (93beb008…) differs from `PRD.md` / `PRD_FINALIZED.md` (09a38ceb…, identical to each other), so the scan demonstrably ran rather than emitting a silent copy. `find implementation -name "*.py" -newer implementation/results.1.json` returns nothing — no implementation file was modified during Steps 8 or 9, so the Step 7 evidence (8/8 rounds at 87/87, failed=0) remains valid for the delivered code. Pipeline complete.
