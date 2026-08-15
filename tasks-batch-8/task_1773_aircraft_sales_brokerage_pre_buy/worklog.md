# Worklog — task_1773_aircraft_sales_brokerage_pre_buy

## Step 1: Create task directory — 2026-08-14T15:05:00.000Z

Pre-assigned by pipeline runner; directory `tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/` verified to exist. Treated as DONE per orchestration args.

## Step 2: Generate Scaffold — 2026-08-14T15:35:47.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Task 1773 — Aircraft Sales Brokerage & Pre-Buy Management

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Entities: 9 (Listing, Buyer, ComparableSale, LOI, Transaction, EscrowDeposit, InspectionFacility, InspectionBooking, DiscrepancyItem)
- State machines: 7 (Buyer, Listing, LOI, Transaction, EscrowDeposit, InspectionBooking, DiscrepancyItem) — LOI carries parallel axes (negotiation status × disclosure status)
- Calculations: 5 (market_comparables_valuation, commission_settlement, deposit_requirement, escrow_disposition_reconciliation, closing_settlement)
- Endpoints: 39 (flat topology under `/api`)
- Errors: 30
- Roles: 5, all `identity: opaque`, peer-roles model (BrokerPrincipal / ListingAgent / BuyerAgent / EscrowOfficer / FacilityScheduler)
- Difficulty instances: 18 (9 rules × 2, all differentiation clauses honored)
- Corner instances: 48 entries (44 active + 4 `excluded_because` stubs)
- Lint: `VERDICT: clean lint` (728 calls scanned; all FKs reverse-reachable)

**Notable design decisions**
- **No logical clock**: all temporal rules are purely geometric (booking overlap), so no `/_clock` test-driving endpoint was needed. Deposit refund-vs-forfeit is state-derived (terminate before vs at DELIVERY_PENDING) rather than wall-clock-based, keeping every rule deterministic.
- **Two interval semantics for Rule 8**: facility bookings require a configurable turnaround buffer (adjacency rejected, gap == buffer allowed); the aircraft itself uses pure half-open overlap (adjacency allowed). Different resources, different geometry.
- **Depth-3 cascade**: close → Transaction CLOSED → Listing SOLD → VERIFIED ComparableSale auto-created from the closing price (feeds back into the valuation input set). Second cascade: LOI accept → Listing UNDER_CONTRACT → sibling LOIs auto-REJECTED.
- **Dual variants with pre-computed literals**: valuation PROVISIONAL 4151152.20 vs FINAL 4137885.95 — comp prices were chosen via a Decimal search so that per-line-round-then-mean (4137885.95) provably diverges from mean-then-round (4137885.94) by exactly one cent, making the pinned rounding order falsifiable. Commission SOLE 344000.01 vs DUAL 466000.02 on base 6100000.25 straddling the 5M tier.
- **OCC (§1.2.1) on two true races only**: LOI counter (legitimate from both SUBMITTED and COUNTERED) and Transaction delivery-conditions PATCH (legitimate in every non-terminal state); all other write-write conflicts were re-classified as state preconditions per the mandatory filter.
- **Priority-conflict pairs** are on different category pairs: {state, business_fiscal} for LOI create vs {state, business_safety} for waiving an already-RESOLVED airworthiness item.

Placeholder closure, name uniqueness across both design files, `excluded_because` target resolution, and forbidden-vocabulary absence were all verified programmatically in addition to the clean lint run.

## Step 3: Copy Shared Files — 2026-08-14T15:35:47.000Z

Copied ./INSTRUCTION.md → tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T15:44:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/PRD.md` generated — 288 lines (the §2.2 "False" in the earlier check was a comparison artifact; line-by-line diff confirms all 48 lines of the canonical block are identical).

## Structure

- **§1 Introduction** — 2 paragraphs (business context → system goals), notes `/api` mount
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (headers, 5 roles, opaque identity prose naming each role), 2.2 Response Structure (verbatim block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (all 9 entities: UUID `id`, `created_at`/`updated_at` 3-fractional-digit UTC, `version`), 2.5 Monetary Precision (2dp round-half-up, positivity/non-negativity constraints), 2.6 OCC (both rules, `ERR_STALE_VERSION` 412), 2.7 State Propagation (cascades/bubble-ups/reverts, immediate consistency), 2.8 Validation Pipeline (10 priorities in order, incl. sub-orderings: state gates a→b→c, facility-before-aircraft, qualified→budget→deposit), 2.9 Identifier Resolution (left-to-right, all nine 404s)
- **§3 Business Logic** — 9 subsections organized by deal pipeline: 3.1 Facilities & turnaround buffers, 3.2 Listings/Comparables/Valuation (PROVISIONAL vs FINAL variants, pinned per-comp rounding), 3.3 Buyer qualification, 3.4 LOI submission/fiscal gates/counter loop/withdrawal, 3.5 Dual-agency disclosure axis, 3.6 Acceptance cascade + auto-reject sweep, 3.7 Escrow funding & inspection scheduling (both conflict rules), 3.8 Discrepancy negotiation (repair/credit/waive, credits recomputation), 3.9 Delivery conditions, closing (commission tiers + dual-agency fee, settlement order pinned), termination (refund vs forfeit), escrow reconciliation invariant
- **§4 Endpoint table** — all 39 endpoints, 4 columns only (Method / Path / Description / Authorized Role)
- **§5 Error catalogue** — all 30 errors, 2 columns only

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs/query params: 70 required, 70 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority pipeline: 10 priorities expressed in order (§2.8), incl. state-gate sub-order, facility-before-aircraft, and qualified→budget→deposit
- concurrency_rules[]: 2/2 expressed (write operation + expected_loi_version / expected_transaction_version + ERR_STALE_VERSION 412), no race-time framing
- state_machines[].transitions: all 7 machines fully expressed (Buyer 1, Listing 4, LOI 6 negotiation + 2 disclosure, Transaction 14, EscrowDeposit 4, InspectionBooking 4, DiscrepancyItem 6) with preconditions, error ids, and every cascade side effect
- calculations[]: 5/5 in precise prose — valuation (both variants, 3-comparable minimum, 0.00004/hour factor, per-comp rounding pinned), commission ($5M tier at 6%/4%, dual +2% of base, single rounding at variant total), deposit (5% of offer, equality passes), escrow invariant (terminal disposes exactly deposit via exactly one channel), closing settlement (commission before settlement, order pinned)
- validations[] conditions: all 31 error ids matchable to triggers in §2/§3 prose
- endpoints[].side_effects / applies_to: all expressed (accept cascade, close cascade, terminate per-state escrow handling, version increments, list filters)
- entities[].fields[] structured content: all defaults/nulls/initial states reconstructible (buffer 120, UNVERIFIED, SUBMITTED, AWAITING_FUNDS, REQUESTED, RAISED, NOT_REQUIRED/PENDING, etc.)
- sibling-branch symmetry: counter both directions, accept/withdraw from SUBMITTED+COUNTERED, terminate from 6 states, cancel from REQUESTED+CONFIRMED, repair/waive from RAISED+COUNTERED — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 366
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage notes

- All formulas translated to prose without operator syntax or fuzzy words; constants embedded in context (three comparables, 0.00004 per hour, five percent deposit, $5M/6%/4%/2% commission, 120-minute default buffer).
- §2.2 verified line-identical to the canonical `section-2.2-response-structure.md` (placeholders `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, empty `data` intact).
- The withheld difficulty/corner design files were not opened or consulted.
- The doc ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T16:09:00.000Z

Complete. All generation and audits done for `task_1773_aircraft_sales_brokerage_pre_buy`.

**Tests emitted: 79 total**
- **Queue A (Difficulty): 36 tests** — all 18 instances covered with exactly 2 tests each. Every instance passed the PRD-first filter (each rule is verbatim-covered in PRD §2.6/§2.8/§3.2–§3.9 and uniquely derived, including the two priority-pair instances, which PRD §2.8 explicitly orders).
- **Queue B (Corner): 43 tests** — all 42 non-stub instances covered with ≥1 test (`activate_with_provisional_only` got a second success-side test). The 6 `excluded_because` stubs were not translated; all 6 cross-references verified to resolve to real difficulty instances.

**Instances skipped: none.** No `skip`/`skipif`/`xfail` markers anywhere.

**Two PRD-first adjustments made during translation (no instances dropped):**
1. `valuation_minimum_three_verified_comps_boundary` — the YAML's pre-computed success literal `4121832.43` contradicts the PRD's pinned FINAL formula on the 4-comp input set; the uniquely-derived value is `4078414.46` (verified via Decimal arithmetic). The test asserts the PRD-derived value; the boundary error path is unchanged.
2. `listing_create_then_get_shows_defaults` — the literal `version == 1` assertion was dropped: PRD §2.4 never pins the initial version number (only "+1 per mutation"), failing the two-reader test. All other assertions (DRAFT/NONE/null estimate) are verbatim-covered. All other version assertions in the suite are relative (captured version + 1).

**Audits (all green):** every test has exactly one `Design:` tag resolving to a real instance; no difficulty instance <2 tests, no corner instance <1 test; every docstring citation contains a ≥8-word substring surviving literal grep of PRD.md; no skip/xfail; `pytest --collect-only` collects 79 tests cleanly.

**Files created:**
- `test_helpers/`: `types.py` (9 entities, 13 enums), `api_client.py` (all 39 endpoints under `/api`), `api_errors.py` (30 errors + framework registration), `assertions.py` (per-entity + escrow disposition invariant + money comparator), `factories.py`, `constants.py` (PRD calculation constants + canonical comp set and worked-example economics), `test_users.py` (5 opaque roles), `fixtures.py` (composite deal pipeline: active listing → accepted deal → funded → inspection scheduled/complete → discrepancy negotiation → delivery pending → closable/closed), `__init__.py`
- `test_suite/`: `conftest.py` + `test_01_listings_and_valuation.py` (14), `test_02_buyers_loi_submission_and_auth.py` (16), `test_03_loi_negotiation_and_acceptance.py` (13), `test_04_escrow_funding_and_booking.py` (14), `test_05_discrepancy_negotiation.py` (9), `test_06_closing_settlement_termination.py` (13)

## Step 6: Generate Implementation — 2026-08-14T16:09:00.000Z

Implementation complete and verified.

**File listing — `tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/implementation/`**

| File | Purpose |
|---|---|
| `start.sh` | Executable launcher: guarded `pip install` (no-op once flask present), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=2.2` |
| `app.py` | App factory, blueprint registration, envelope error handlers (ApiError/404/405/500), global RLock for deterministic OCC under threaded dev server |
| `db.py` | Empty in-memory store (9 collections + insertion seq) — no seeding |
| `errors.py` | All 30 catalog error IDs with exact HTTP statuses |
| `response.py` | Envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth, 5 roles, 401/403 |
| `validate.py` | Schema validators (money as `Decimal` with 2dp half-up enforcement, ints/bools/enums/ISO datetimes), pagination (default 10, clamp 1–100) |
| `services/core.py` | Record lifecycle (version=1 at create, +1 per mutation incl. cascades), field-whitelist serializers (Decimal→float), list/filter/paginate helper |
| `services/valuation.py` | PROVISIONAL plain mean; FINAL per-comp time adjustment (0.00004/hr) rounded per comp before averaging; ≥3 VERIFIED exact make+model comps |
| `services/settlement.py` | Tiered commission (6% ≤$5M, 4% above; +2% of base for dual agency, rounded once at variant total), settlement pair, 5% deposit minimum |
| `services/scheduling.py` | Facility buffer conflict (buffer-expanded window intersection), aircraft half-open overlap (adjacency allowed), active-booking scan |
| `routes/` | 9 modules: facilities, listings, buyers, comps, lois, transactions, escrow, bookings, discrepancies |

**Endpoint coverage: 39/39** — registered route count matches the scaffold endpoint table exactly, including the nested `POST /api/transactions/{id}/discrepancy-items` and the PATCH delivery-conditions endpoint.

**Boot verification**
- 3 consecutive fresh-process `bash start.sh` invocations (simulating per-test-server isolation): each served HTTP 200 within ~1–2 s with an empty store (`total_count=0`); well within the 60 s contract.
- A 120-assertion end-to-end smoke run passed covering: envelope shape, auth/role errors, schema 400s, 404s, PROVISIONAL/FINAL valuation math (numerically verified divergence), activation gate, fiscal gates in pinned order (deposit boundary equality passes), counter-loop OCC 412, dual-agency disclosure axis (PENDING→PARTIAL→FULLY_ACKED, double-ack 409), acceptance cascade (transaction+escrow created, listing UNDER_CONTRACT, sibling auto-reject with version bumps), escrow fund bubble-up, booking window/facility/aircraft conflicts, confirm/complete/cancel bubble-ups and revert, discrepancy lifecycle (counter/agree-credit/commit-repair/waive, `ERR_AIRWORTHINESS_NOT_WAIVABLE`, `ERR_CREDIT_NOT_PROPOSED`), credits recomputation, delivery-conditions OCC, closing with numerically verified sole (812000.00) and dual (639400.00) commission, escrow release/refund/forfeit dispositions, closing-minted VERIFIED comparable, and pagination.

**Judgment calls (spec ambiguity resolved)**
- Disclosure `party` accepted case-insensitively (`buyer`/`seller`) — PRD doesn't pin literal enum values.
- Booking confirm/complete transaction-gate failures → `ERR_TRANSACTION_NOT_FUNDED` (409).
- Raising a discrepancy gated to `INSPECTION_COMPLETE`/`DISCREPANCY_NEGOTIATION` → `ERR_INVALID_STATE`.
- No entity seeding anywhere at startup; test harness drives all state through the API.

## Step 7: Run Tests and Iterate — 2026-08-14T16:20:00.000Z

All 8 rounds pass cleanly: 79/79 in every round. Exiting with the summary.

**Iterations run:** 2 (sweep 1: 77/79 in all 8 rounds with 2 deterministic failures; fixes applied; sweep 2: 79/79 in all 8 rounds, zero flakes).

**Tests deleted:** None.

**Diagnosis of the two failures (both deterministic across all 8 rounds):**

1. `test_01_listings_and_valuation.py::TestMinimumComparablesBoundary::test_valuation_with_third_verified_comp_succeeds` — expected 4078414.46, got 4121832.43. PRD §3.2 covers the rule verbatim ("Only `VERIFIED` comparables ever enter a valuation's input set" plus the pinned FINAL rounding order). STEP 2 found the test wrong: the expected constant `EXPECTED_FINAL_VALUE_FOUR_COMPS` included the adjusted value (3948160.55) of the UNVERIFIED 3980000.55 comp in the average — contradicting the VERIFIED-only input-set rule quoted in the test's own docstring. The PRD-faithful value over the 3 VERIFIED comps is (4106797.29 + 4358700.00 + 3900000.00) / 3 = 4121832.43, exactly what the implementation returned.

2. `test_05_discrepancy_negotiation.py::TestAcceptAsIsGate::test_accept_as_is_with_open_items_returns_open_discrepancies` — expected ERR_OPEN_DISCREPANCIES, got ERR_INVALID_STATE. PRD §3.9 covers it verbatim ("...only while zero discrepancy items exist for the transaction — otherwise it is rejected with `ERR_OPEN_DISCREPANCIES` (HTTP 409)") and §2.8 step 5(b) explicitly catalogs "zero findings for as-is acceptance (`ERR_OPEN_DISCREPANCIES`)". Unique derivability holds: §3.8's cascade (first finding moves the transaction INSPECTION_COMPLETE → DISCREPANCY_NEGOTIATION) makes "findings exist" and "tx in DISCREPANCY_NEGOTIATION" the same reachable scenario, so the implementation's strict state-first check rendered the PRD-cataloged gate permanently unreachable. The test (setup + request + assertion) was faithful; the implementation was wrong.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/test_helpers/constants.py` — `EXPECTED_FINAL_VALUE_FOUR_COMPS` corrected 4078414.46 → 4121832.43 (3-VERIFIED-comp mean per PRD §3.2; UNVERIFIED comp excluded), comment updated.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/test_suite/test_01_listings_and_valuation.py` (test_valuation_with_third_verified_comp_succeeds) — arithmetic comment and assertion message corrected to the three-VERIFIED-comp input set; assertion itself unchanged in form.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/implementation/routes/transactions.py` (`accept_as_is`) — the zero-findings gate now fires ERR_OPEN_DISCREPANCIES for a DISCREPANCY_NEGOTIATION transaction (the only reachable state with findings, per PRD §3.8) and for the defensive INSPECTION_COMPLETE-with-items case; all other non-source states (including terminal, preserving §3.9's terminal rule) still yield ERR_INVALID_STATE. No PRD-required check was weakened; happy-path accept-as-is (INSPECTION_COMPLETE, zero items → DELIVERY_PENDING) unchanged, as confirmed by the other accept-as-is consumers (`setup_delivery_pending_deal`, test_03, test_06) passing in all rounds.

## Step 8: Finalize PRD — 2026-08-14T16:27:00.000Z

Done. `PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/PRD_FINALIZED.md` with exactly one revision.

**Line counts / delta:** PRD.md = 287 lines, PRD_FINALIZED.md = 287 lines (0% line delta; +442 chars, +1.04% by characters). Single-line in-place revision at line 195.

**Changes:**
- §3.9 — revise — split the as-is acceptance sentence to pin gate precedence: a `DISCREPANCY_NEGOTIATION` transaction is rejected with `ERR_OPEN_DISCREPANCIES`, not `ERR_INVALID_STATE` (the zero-findings gate decides there, since §3.8's first-finding cascade puts every with-findings transaction in that state); an attempt from any other state besides `INSPECTION_COMPLETE` and `DISCREPANCY_NEGOTIATION` — including terminal states — yields `ERR_INVALID_STATE` — `workspace/implementation/routes/transactions.py:112-123`.

**Step-7 items disposition:**
- Item 1 (`EXPECTED_FINAL_VALUE_FOUR_COMPS` 4078414.46 → 4121832.43): pure test-fixture bug. `implementation/services/valuation.py:25-31,48-56` already implements PRD §3.2 verbatim (VERIFIED-only input set, per-comp rounding before averaging). No PRD edit.
- Item 2 (`accept_as_is` implementation fix): the one edit above. The PRD's §2.8 pipeline (5a state check before 5b domain gates) plausibly read as `ERR_INVALID_STATE`-first for a `DISCREPANCY_NEGOTIATION` transaction — exactly what the pre-fix implementation built — so the fixed precedence is now pinned in §3.9.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) Subject: accept-as-is endpoint gating — which transaction states succeed, which error fires per state, and precedence of the zero-findings gate vs. the source-state check.
- (b) Impl paths enumerated and read/grepped: `routes/transactions.py:98-126` (`accept_as_is` — the only raise site of `ERR_OPEN_DISCREPANCIES`, confirmed by repo-wide grep); `routes/transactions.py:29-36` (state constants, unused by `accept_as_is`); `routes/discrepancies.py:82-137` (`create_item`: findings raisable only in `INSPECTION_COMPLETE`/`DISCREPANCY_NEGOTIATION`; first finding flips state at lines 134-136); `routes/discrepancies.py:49-79` (`_resolve` bubble-up to `DELIVERY_PENDING` only when all items RESOLVED); grep for `del/pop/remove` on discrepancies (no delete path — items persist forever); `routes/bookings.py:158` (only entry into `INSPECTION_COMPLETE`); `errors.py:22,55` (error catalog); all `DELIVERY_PENDING` transition sites (transactions.py:124, discrepancies.py:76 — no others); auxiliary: `test_suite/test_05:82-92`, `test_03:304`, `test_06:182,288`, `test_helpers/fixtures.py:287`, `api_client.py:91-93`.
- (c) Wording adjustment: yes. Initial draft keyed the gate on item existence ("whenever any discrepancy items exist → `ERR_OPEN_DISCREPANCIES`"), which would have mis-described the off-site path of a `DELIVERY_PENDING` transaction retaining resolved findings — the impl returns `ERR_INVALID_STATE` there (transactions.py:119-123). Revised to key the gate on state (`DISCREPANCY_NEGOTIATION`, plus the defensive `INSPECTION_COMPLETE`-with-items case via the preserved "otherwise" clause) and to explicitly assign all other states — including terminal ones, consistent with §3.9's existing terminal rule — to `ERR_INVALID_STATE`, matching every enumerated impl path.

## Step 9: Complete PRD — 2026-08-14T16:38:00.000Z

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1773_aircraft_sales_brokerage_pre_buy/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (287 lines, 42,976 chars) → `PRD_COMPLETED.md` (291 lines, 46,913 chars). Delta: +4 lines, +3,937 chars. All edits are in-paragraph inserts/revisions except two short clarifying paragraphs appended inside §2.2; no new sections, no invented behavior.

**Counts:** 22 ambiguity-pins (20 inserts + 2 in-place revisions of ambiguous prose), 3 mismatch-revisions.

**Changes:**

- §2.2 — insert — ambiguity — undeclared routes/unsupported methods return the error envelope with `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) — implementation/app.py:63-71
- §2.2 — insert — ambiguity — action endpoints return the path-addressed resource in `data` (LOI for accept, transaction for close/terminate, etc.); cascaded changes read via own endpoints — routes/lois.py:208, routes/transactions.py:158,212
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to ≥0), non-integer values rejected with `ERR_VALIDATION`; `created_at` ties broken by creation order; `has_more` = `offset + returned < total_count` — validate.py:165-185, response.py:30, services/core.py:110
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — services/core.py:70
- §2.5 — revise — mismatch — monetary inputs with more than two decimal places are rejected with `ERR_VALIDATION` (400), not rounded for the caller — validate.py:92-97
- §2.5 — insert — ambiguity — `new_price_usd` added to must-be-positive money; `qualified_budget_usd` and `proposed_credit_usd` may be zero but never negative; `year` is an integer with no range restriction — routes/lois.py:124, routes/buyers.py:38, routes/discrepancies.py:160, routes/listings.py:37
- §2.6 — revise — mismatch — LOI counter rejects any version inequality (supplied version ahead or behind), not only a version "advanced beyond" — routes/lois.py:131-135
- §2.7 — revise — mismatch — cascaded effects are applied atomically within the request and observable by subsequent reads (the response body carries only the path resource), replacing "visible within the same request's response" — routes/lois.py:163-208, routes/escrow.py:50-58
- §2.8 step 4 — insert — ambiguity — a request body that is not a JSON object (incl. malformed JSON) is a schema failure under `ERR_VALIDATION` — validate.py:18-24
- §3.2 — insert — ambiguity — a valuation may be requested for a listing in any status — routes/listings.py:55-65
- §3.3 — insert — ambiguity — both qualification inputs required; qualifying an already-QUALIFIED buyer rejected with `ERR_INVALID_STATE` (409) — routes/buyers.py:38-41
- §3.5 — insert — ambiguity — `party` matched case-insensitively against `buyer`/`seller` (else `ERR_VALIDATION`); acknowledgment not gated on the LOI's negotiation status — routes/lois.py:230-246
- §3.7 — insert — ambiguity — `funding_reference` is a required string; the OPENED→ESCROW_FUNDED bubble fires only while the transaction is still OPENED (funding after an OPENED-termination moves only the deposit) — routes/escrow.py:44,55-57
- §3.7 — insert — ambiguity — booking `start_at`/`end_at` stored and returned verbatim; parsed as ISO 8601 with timezone-less values read as UTC — routes/bookings.py:58-59,94-100, util.py:29-39
- §3.7 — revise — ambiguity — facility buffer expands existing windows on both sides; a gap of exactly `turnaround_buffer_minutes` is permitted — services/scheduling.py:19-32
- §3.7 — insert — ambiguity — confirm with transaction outside ESCROW_FUNDED/INSPECTION_SCHEDULED rejected with `ERR_TRANSACTION_NOT_FUNDED` (409) — routes/bookings.py:127-132
- §3.7 — insert — ambiguity — complete with transaction not INSPECTION_SCHEDULED rejected with `ERR_TRANSACTION_NOT_FUNDED` (409) — routes/bookings.py:150-154
- §3.8 — insert — ambiguity — findings raisable only in INSPECTION_COMPLETE/DISCREPANCY_NEGOTIATION, else `ERR_INVALID_STATE` (409) — routes/discrepancies.py:102-107
- §3.8 — insert — ambiguity — referenced booking's own status is not gated; only its belonging to the transaction is checked — routes/discrepancies.py:109-118
- §3.8 — insert — ambiguity — `repair_offer_note` is accepted but not persisted and never appears on the item's representation — routes/discrepancies.py:161
- §3.8 — insert — ambiguity — a resolution that changes neither `credits_total_usd` nor status leaves the transaction's `version`/`updated_at` untouched — routes/discrepancies.py:68-79
- §3.9 — insert — ambiguity — `tax_planning_notes` accepts a string or explicit null (clears the note) — routes/transactions.py:75,92-93
- §3.9 — insert — ambiguity — every successful delivery-conditions request increments `version`, even with no field change — routes/transactions.py:94
- §3.9 — revise — ambiguity — minted comparable's `sale_date` is the server's current UTC date at closing; the close request carries no body input — routes/transactions.py:206, util.py:24-26
- §3.9 — insert — ambiguity — terminate's `reason` is a required string — routes/transactions.py:134

**Notable findings during the walk:** the implementation reuses `ERR_TRANSACTION_NOT_FUNDED` for the booking confirm/complete transaction-state gates (previously unpinned error choice); `repair_offer_note` is silently discarded rather than persisted; and the delivery-conditions PATCH bumps `version` even on no-op updates — all now pinned in the PRD.
