# Worklog — task_1102_household_goods_van_line_agent_network

## Step 1: Create task directory — 2026-08-10T15:15:43.337Z

Task directory `tasks/task_1102_household_goods_van_line_agent_network/` and its `workspace/` subdirectory pre-assigned and already present (created by the outer pipeline); Step 1 auto-index scan skipped per instructions. Recorded as done.

## Step 2: Generate scaffold — 2026-08-10T16:12:54.484Z

Scaffold generation complete for task 1102. All three artifacts are on disk and the skill's lint passes clean on the first run.

### Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/SCAFFOLD.yaml` (115 KB) — §1.0–§1.7 only, no design keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (118 KB) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/SCAFFOLD_CORNER_DESIGN.yaml` (171 KB) — single top-level key `scaffold_corner_design`

### SCAFFOLD.yaml counts
- **15 entities**: Agent, Customer, Tariff, MoveOrder (dual-axis status × billing_status), Estimate (self-referential supersede chain), OrderAgentAssignment (junction), ValuationCoverage, WeightTicket (immutable event), ReweighRequest, Warehouse, SITLot, CrewAssignment, RevenueStatement, Claim, Dispute (polymorphic claim/statement subject)
- **80 endpoints**, incl. `POST /_clock/set_current_utc` (default 2026-05-01T00:00:00Z) and full FK reverse-reachability GETs
- **50 error codes**, **18 ordered validation rows** (auth → authz/ownership → existence → state → safety/segregation → temporal → constraint → referential → fiscal), **10 calculations**, **12 state machines**, **8 roles** (4 entity-backed agent roles + Customer; opaque VanLineAdmin/ClaimsAdjuster/Arbitrator), **2 OCC concurrency rules** (estimate-create and valuation-elect, both supersede races on MoveOrder.version)

### Difficulty design (§1.8): 18 instances, 2 per rule, all differentiated per §0.5
- dual_variant_calc: MoveOrder billing (binding vs non-binding) × Claim settlement (released vs FVP) domains
- combinatorial_formula: mode (a) revenue-split waterfall with binding van-line floor vs mode (b) pinned per-component rounding (495784 vs 495783 cent-splitting case)
- non_linear_state_machine: MoveOrder IN_TRANSIT⇄IN_SIT cycle vs Claim OFFER_MADE⇄DISPUTED negotiation loop
- transitive_cascade: deliver→statement→assignment→agent-ledger (depth 3) vs arbitration decide→claim→chargeback/quality (different trigger)
- priority conflicts: (state, fiscal) on deliver vs (existence, referential) on register
- boundary precision: exact 110% cap / zero deferred (money, deliver) vs SIT day-179/180 auto-conversion (day count, sit-lots)
- cross-entity gates: MoveOrder×Estimate book gate vs Claim×MoveOrder filing gate
- overlap semantics: crew half-open adjacency (Agent) vs warehouse aggregate capacity (Warehouse)
- compensating invariants: warehouse cwt roundtrip vs agent-date confirmed crew-hours roundtrip

### Corner design (§1.9): 43 instances (39 active + 4 valid excluded stubs) across all 9 guide sections
Covers defaults/computed fields, FK filter listings, invalid transitions, terminal lockdown, cancel compensation cascade, tariff window adjacency, estimate expiry at exact second, 270-day claim window, reweigh uniqueness/expiry, dispute xor gates, RBAC denial + ownership scoping + two segregation-of-duties tests, both OCC stale-version paths, envelope/pagination, immediate consistency. All formula-derived asserts precomputed as literals.

### Lint status (verbatim verdict)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(1130 calls scanned; 18 §1.8 + 39 active §1.9 instances.) Additional self-checks passed: key separation, all 61 instance names unique across both design files, no forbidden race vocabulary, scenario text verbatim, excluded stubs reference real difficulty instances.

One design fix worth noting: during §1.9 authoring I found and repaired a self-contradiction — the original draft both blocked delivery on PERFORMED re-weighs and cascaded them to EXPIRED at delivery (deadlock). Final rule: REQUESTED re-weighs block delivery (ERR_REWEIGH_PENDING, customer must cancel); PERFORMED-but-unapplied re-weighs auto-expire at delivery with original weight standing.

## Step 3: Copy shared files — 2026-08-10T16:13:19.220Z

Copied ./INSTRUCTION.md → tasks/task_1102_household_goods_van_line_agent_network/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T16:32:00.000Z

The PRD is complete and verified. All constraint files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, other task_* directories) were never opened.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/workspace/PRD.md` — 390 lines, 65,719 bytes, verified on disk.

**Section list:**
- §1 Introduction (3 paragraphs: agent-network business context, system scope, financial discipline)
- §2 Global Specifications: 2.1 RBAC (8 roles with per-role `identity:` prose), 2.2 API Response Structure (verbatim fixed block incl. `req_RANDOMALPHANUM123456`), 2.3 Pagination + all 15 list-filter sets, 2.4 Common Resource Properties (WeightTicket `updated_at`/`version` absence called out), 2.5 Logical Clock (default 2026-05-01T00:00:00Z, `to_iso8601`, `current_utc`, SIT re-evaluation side effect), 2.6 Money/Weight/Rounding (integer cents, round-half-up, pinned round-per-component-then-sum, cwt round-up), 2.7 OCC (both `expected_order_version` rules), 2.8 Half-Open Intervals (tariff windows, mileage bands, crew hours), 2.9 Network Ledgers (occupied_cwt, ytd earnings, quality score), 2.10 Validation Pipeline (12 ordered stages mapping priorities 1–18)
- §3 Business Logic (9 subsections): 3.1 onboarding (agents/customers/tariffs/warehouses), 3.2 order registration + staffing, 3.3 estimates + valuation premiums, 3.4 book/weigh/dispatch, 3.5 re-weighs + SIT (180-day conversion, delivery-blocking nuance), 3.6 crew labor (8-hour overtime rule, half-open conflicts), 3.7 delivery + 110% cap + payments + close/cancel, 3.8 revenue waterfall (base pcts, tier bonuses, 4% van-line floor absorbed by HAULING, conservation invariant), 3.9 claims/disputes/arbitration (dual-variant cap, 3-round cap, segregation of duties, 80%/20% integer cross-multiplication fee allocation)
- §4 Endpoint table — 80 rows, 4 columns only
- §5 Error catalogue — 50 rows, 2 columns only, no trigger conditions

**Hard-contract audit:**
- Contract 1 (Field-Name Coverage): 138 required identifiers (all `entities[].fields[].name`, every `request_body`/`query_params` name incl. `to_iso8601`, `terminal`, `expected_order_version`, `amount_cents`, `reason`, `response_note`, `capability`, envelope tokens) — 138 present in backticks, 0 missing. PASS
- Contract 2 (Rule Coverage): validation priorities 18/18 expressed (pipeline §2.10 + written evaluation orders for book/dispatch/deliver/SIT-release in §3); OCC rules 2/2 (write operation + `expected_order_version` + `ERR_STALE_ORDER_VERSION`/412 all named, no race framing); state-machine transitions all expressed incl. system cascades (supersession unlatch, deliver 3-hop cascade, finalize cascade, decide dual-subject cascade); calculations 10/10 in reconstructible prose with all constants embedded; validation conditions 18/18 matchable to their exact error IDs (incl. 422-vs-409 distinctions); endpoint side effects 80/80 covered in narrative; field structured content (defaults, nullability windows, forced-zero rules) stated; sibling branches symmetric (dual cancel, dual deliver, triple withdraw, dual supersede). PASS
- Contract 3 (§3 Path Purity): 670 backtick tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS

Additional checks: all 50 error IDs appear in §2/§3 prose and in §5; all 66 state/enum values appear as exact backticked strings; no operator syntax (`==`, `>=`, `+=`, `ceil(`, etc.) anywhere in prose.

## Step 5: Generate unit tests — 2026-08-10T17:12:23.795Z

All generation and verification complete.

### Summary

**Task**: task_1102_household_goods_van_line_agent_network — full test infrastructure + suite generated from the two design indices only.

#### test_helpers/ (9 modules)
- `types.py` — 14 entity TypedDicts + status/role enums; `WeightTicket` correctly omits `updated_at`/`version` (common_fields: false)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (58 methods)
- `api_errors.py` — all 51 error ids + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus warehouse-occupancy, waterfall-conservation, quality-score invariant checkers
- `factories.py` — payload factories with collision-free unique codes/emails
- `constants.py` — PRD thresholds (SIT 180d, cap 1.10, role/tier tables, 85¢/unit FVP rate, 3 rounds, 14d cooling-off, 270d window, 25000 fee, OT 8h/1.5x)
- `test_users.py` — `TEST_USERS` + per-instance `make_*_headers` builders for all entity-backed roles
- `fixtures.py` — composite fixtures: network/registered/booked/in-transit/delivered order chains, SIT setup, claim/dispute/docketed-dispute chains, plus PRD-faithful pricing mirrors (`compute_linehaul_cents`, `compute_delivery_amounts`, `compute_split_shares`) used to pre-compute lawful delivery collection amounts — verified against the design indices' expected values (495784, 570240/522720/47520, waterfall 57024/119750/313632/57024/22810)
- `__init__.py` — barrel export

#### test_suite/ — 75 tests in conftest.py + 11 files
- Queue A (Difficulty): **18/18 instances, each with exactly 2 tests (36 tests)**
- Queue B (Corner): **39/39 non-stub instances, each ≥1 test (39 tests)**; the 4 `excluded_because:` stubs untranslated, all cross-references resolve to real difficulty instances

#### Skips / deviations (PRD-first filter)
- No instance fully skipped. Three documented adjudications:
  1. `Corner/validations/agent_capability_and_suspension_gates` — suspension-confirm leg dropped: PRD §3.2 names `ERR_AGENT_SUSPENDED` only for assignment ("assigning to a SUSPENDED or TERMINATED agent is rejected"), while confirm says only "the agent must still be ACTIVE" with no error id (fails unique derivability). Capability leg fully tested.
  2. `Corner/entities/self_referential_estimate_revision_chain` — the YAML's literal `estimated_charges_cents == 490500` is arithmetically inconsistent with its own derivation (405000+40500+5000=450500); test asserts the PRD-derived 450500.
  3. Absolute initial-version assertions (`version == 1`) dropped from two corner tests — PRD §2.4 pins only "+1 per mutation", never the initial value; relative increments asserted instead.

#### Verification results
- `python3 -m py_compile`: all 20 files pass
- pytest collection: **75 tests collected**
- Design-tag audit: every test has exactly one `Design:` tag as the last docstring line; all 75 tags resolve to real instances; zero tags point at stubs — **PASS**
- Citation audit: all 75 docstring PRD citations verified verbatim (8-word sliding window) against `workspace/PRD.md` — **PASS**
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code

## Step 6: Generate implementation — 2026-08-10T17:12:23.795Z

Implementation complete and verified. Summary:

### Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/workspace/implementation/`)

- `start.sh` — executable, guarded `pip install` (no-op when flask importable), `exec python3 app.py` foreground
- `requirements.txt` — flask>=2.2
- `app.py` — Flask entry (static folder disabled), global RLock via before/teardown request, enveloped ApiError/404/405/500 handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores for all 16 entity types + logical clock (default 2026-05-01T00:00:00Z) + order sequence; **empty at boot, no seeding anywhere**
- `errors.py`, `response.py` — ApiError + exact envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more`)
- `middleware.py` — X-User-ID/X-User-Role auth (401), 8-role authorization with entity-backed identity resolution (403), order-ownership scoping
- `util.py` — ISO-8601 parse/format (3-fractional-digit Z), Decimal round-half-up, body validation (unknown-field rejection, typed fields, enum/int-range), pagination
- `services/calc.py` — all 10 calculation rules (linehaul cwt/bands, pinned component rounding, valuation premium tiers, 110% cap, spread window, SIT accrual/180-day cap, crew OT, revenue waterfall with HAULING-absorbed floor, claim caps, integer-cross-multiplication fee allocation)
- `services/store.py`, `services/lifecycle.py` — entity factories/serializers (WeightTicket gets only id+created_at) and cascades (deliver 3-hop, chargeback→quality_score, SIT conversion, claim settle)
- `routes/` — core.py (clock, agents, customers, tariffs, warehouses), orders.py, estimates.py (estimates + valuation coverages), assignments.py, transit.py (weight tickets, reweighs, SIT lots), crews.py, settlement.py (statements, claims, disputes)

### Endpoint count vs scaffold

**80 / 80** — programmatic diff of the Flask url_map against SCAFFOLD.yaml §1.5: zero missing, zero extra.

### Verification results

- `python3 -m py_compile` passes on all 19 source files.
- Smoke boot per contract (`PORT=<free> timeout 8 bash start.sh &`): boots in ~2s, serves enveloped 200/404/401/clock-set responses correctly.
- Full lifecycle test passed end-to-end: order → estimate (OCC 412 verified) → coverage (premium 3613 verified) → supersede/accept → staffing/confirm (split_pct snapshots) → book (spread window dates) → crew OT invoice (100000) → weigh → dispatch gates (422 pickup-date) → SIT check-in/accrual/release → deliver with waterfall (floor deficit 8250 correctly carved from HAULING; conservation invariant holds) → finalize → SETTLED/INVOICED → claim → dispute → 14-day cooling-off 422 → arbitration decide (RESPONDENT fee, claim cascade, chargeback 90000 → quality 91) → pay (SoD) → reconcile → close.
- Edge suite passed: duplicate codes, tariff overlap/adjacency, band tiling 400s, book-gate ordering, capability/suspension, release-BOOKING rejection, crew conflict/adjacency, service-window 422, reweigh-pending/already-used/not-performed, 180-day auto-conversion on read + `ERR_LOT_NOT_IN_STORAGE`, estimate expiry flip to EXPIRED, claim-window, dispute XOR, segregation-of-duties.

### Judgment calls / known gaps (spec ambiguities resolved deliberately)

1. **Ownership scope vs late-state sweeps** — §2.1 limits scope to PROPOSED/CONFIRMED assignments, but that makes the documented state errors (e.g. deliver-from-DELIVERED → `ERR_TRANSITION_NOT_ALLOWED`, book-from-CANCELLED → `ERR_ORDER_NOT_REGISTERED`) unreachable for the legitimate role holder whose assignment is by then COMPLETED/RELEASED. I made generic order-scope status-blind (agent+role+order match); explicit identity rules (assignment confirm, crew confirm/complete, dispute filer) remain as written.
2. **Deliver from IN_SIT after 180-day conversion** — allowed when no lot remains IN_STORAGE, reconciling the §3.5 note ("a CONVERTED_PERMANENT lot does not block delivery") with §3.7's from-state list.
3. **Body-reference existence (404) vs body well-formedness (400)** — well-formed string ids are resolved (404) before full field validation; missing/wrong-typed reference fields fall through to 400, matching the pipeline for all single-fault cases.
4. Arbitration-decide claim cascade leaves the last negotiated `offer_amount_cents` untouched; only `settled_amount_cents`/`offered_by_user_id` are overwritten, per PRD §3.9.

## Step 7: Run tests and iterate — 2026-08-10T17:35:35.678Z

All 8 rounds pass 75/75 with zero failures. The loop is complete.

### Summary

**Iterations run: 2** (iteration 1: 12 tests failing deterministically in all 8 rounds, 63/75; iteration 2 after fixes: **all 8 rounds 75/75 passed** — clean exit).

**Tests deleted: none.** Every failing test traced to verbatim PRD prose with uniquely determined outcomes.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/test_helpers/fixtures.py` — `register_order` now returns the created order (was returning the ctx dict; three tests in test_02/test_03 index `["id"]`/`assert_move_order` on the return value). `setup_registered_order` keeps returning ctx.
- Same file — added `book_additional_order` / `in_transit_additional_order` / `delivered_additional_order` (+ `_share_network`): register additional orders against an existing network's one published tariff. PRD §2.8 forbids publishing a second tariff whose window intersects an already-published one, and §3.2 requires the backing tariff's window to cover the pickup date — so multi-order tests cannot each publish their own identical-window tariff (the root cause of the 4 `ERR_TARIFF_WINDOW_OVERLAP` setup failures).

**Fixes applied to `test_suite/`:**
- `test_05_tariffs.py` — added missing `validate_success` import (NameError in `test_tariff_window_overlap_with_adjacency_allowed`).
- `test_09_delivery_and_revenue.py` — `_setup_registered_with_destination_assignment` now takes `api` as a parameter (module-level helper referenced the pytest fixture by name → NameError); call site updated; `test_non_binding_final_charges_recomputed_with_cap` builds its second order via `delivered_additional_order` on the shared tariff.
- `test_11_disputes_arbitration.py` — `_setup_final_statement(api)` and `_run_revenue_dispute(api, ...)` now take `api` as a parameter; both call sites in `test_arbitration_fee_allocation_thresholds` updated.
- `test_06_order_lifecycle.py` — `test_delivery_spread_mileage_band_boundary` builds its second booked order via `book_additional_order` on the shared tariff.
- `test_07_sit_and_reweigh.py` — `_setup_three_in_transit_orders` builds orders 2–3 via `in_transit_additional_order` on ctx1's shared tariff.
- `test_03_estimates.py` — `test_estimate_revision_chain_and_supersede` now passes `tariff_overrides={"mileage_bands": SIMPLE_TARIFF_BANDS}`: the pinned assertion (90 cwt × 4500 × 1.0 + 40500 fuel + 5000 packing = 450500) assumes multiplier 1.0, but the default fixture bands apply 1.2 at 900 miles (→ 539600); the setup was inconsistent with the test's own derivation.

**Fixes applied to `implementation/`:**
- `util.py` — added `fmt_date` (renders `YYYY-MM-DDT00:00:00Z`) and `midnight` (midnight-UTC normalization). PRD §2.5: "Fields that carry a calendar date rather than an instant — the order's `pickup_date` and a crew assignment's `service_date` — use day precision at midnight UTC (00:00:00Z)"; the three-fractional-digit form is reserved by §2.2/§2.4 for server-stamped instants (`api_request_timestamp`, `created_at`, `updated_at`).
- `services/store.py` — `order_view` renders `pickup_date`/`earliest_delivery_date`/`latest_delivery_date` and `crew_view` renders `service_date` via `fmt_date` (spread dates are whole-day arithmetic on midnight-normalized dates per §3.4/§2.5). This fixed `test_book_after_accept_computes_spread_window` (`2026-06-14T00:00:00.000Z` vs `...00:00:00Z`).
- `routes/orders.py` / `routes/crews.py` — midnight-normalize `pickup_date`/`service_date` at ingest per §2.5 day-precision rule.

## Step 8: Finalize PRD — 2026-08-10T17:40:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/workspace/PRD_FINALIZED.md` is written.

### Summary

**Line counts:** PRD.md 390 lines, PRD_FINALIZED.md 390 lines (0% delta — one sentence revised in place, no lines added or removed; the paragraph grew within the same line).

**Changes (one total):**

- **§2.5 — revise —** Expanded the day-precision sentence to pin three things the implementation fixes revealed but PRD left open: (1) `earliest_delivery_date`/`latest_delivery_date` are day-precision fields too (they are computed by whole-day arithmetic from the midnight-normalized `pickup_date` and rendered `T00:00:00Z`); (2) client-supplied `pickup_date`/`service_date` values carrying a time-of-day are normalized to midnight UTC at intake, and the normalized value drives all storage, comparisons, and computation; (3) these four fields render as `YYYY-MM-DDT00:00:00Z` with no fractional digits, with the three-fractional-digit form reserved for instant fields. — `implementation/util.py:23-38`, `implementation/services/store.py:42-44,91`, `implementation/routes/orders.py:35`, `implementation/routes/crews.py:37`, `implementation/services/calc.py:71-77`

**Items from the diff that needed no PRD edit (verified):** `register_order` returning the created order (PRD §4 already pins create-returns-resource); the `*_additional_order` fixture helpers sharing one published tariff (PRD §2.8 line 111 and §3.2 line 160 already determine this); all test-suite fixes (pure test bugs — missing import, missing `api` parameters, and the estimate-chain mileage-band override where PRD §3.3's multiplier rule was already pinned).

**Per-edit pre-edit search log:**

- **Edit 1 (§2.5 sentence):**
  - **(a) Subject:** day-precision date fields — membership, ingest normalization, response rendering form, day arithmetic.
  - **(b) Impl paths enumerated and read/grepped:** `util.py:16-38` (`fmt_ts`/`fmt_date`/`midnight`); `services/store.py` in full (all serializers — confirmed exactly four `fmt_date` fields: order `pickup_date`/`earliest_delivery_date`/`latest_delivery_date` at lines 42-44, crew `service_date` at line 91; everything else — `effective_start`/`effective_end`, `delivered_at`, `issued_at`/`expires_at`, `weighed_at`, `checked_in_at`/`released_at`, `filed_at`, `responded_at`/`escalated_at` — uses `fmt_ts` or plain data); `routes/orders.py:32-39,124-126,148-150` (ingest normalization, tariff-window coverage on the normalized value, spread-window write, dispatch gate); `routes/crews.py:30,37,49-54,87` (ingest normalization, service-window check, schedule-conflict date equality); `routes/core.py:25,206-226,250` (tariff `effective_start`/`effective_end` and clock `to_iso8601` are NOT midnight-normalized — confirms the normalization claim must be scoped to the two ingestible day-precision fields, not all datetime inputs); `routes/transit.py:21` (`weighed_at` not normalized); `services/calc.py:71-77` (whole-day `timedelta(days=...)` on the normalized pickup_date); `services/lifecycle.py` (no date-field handling); `response.py:9` (`api_request_timestamp` via `fmt_ts`). Also grepped test suite/helpers to confirm tests only ever send midnight dates, so ingest normalization is impl-only behavior needing a PRD pin.
  - **(c) Wording adjustment:** Scoped the rendering claim to the four named fields rather than a universal "all day-precision fields" rule; scoped ingest normalization explicitly to the two client-supplied fields (`pickup_date`, `service_date`) since the two spread dates are never client-supplied; kept the original "whole-day arithmetic" clause verbatim; deliberately did NOT pin that the tariff-window coverage comparison uses the normalized value (it does — `orders.py:37` — but §3.2's existing "cover the pickup date" already reads consistently, and over-specifying there risked a new mismatch with no Step-7 justification). No other PRD sections touched: §3.2/§3.4/§3.6 phrasing ("pickup date plus the transit days", "cover the pickup date", service-window bounds) remains accurate under the revised §2.5.

## Step 9: Complete PRD — 2026-08-10T17:50:00.000Z

Task complete. `/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network/workspace/PRD_COMPLETED.md` written.

### Summary

**Source/delta**: PRD_FINALIZED.md 390 lines / 66,426 chars → PRD_COMPLETED.md 390 lines / 68,872 chars (+0 lines, +2,446 chars). All edits are in-paragraph; no sections added.

**Counts**: 9 ambiguity-pins, 3 mismatch-revisions (12 total changes).

**Changes** (section — kind — class — what — impl ref):

1. §2.1 — revise — **mismatch** — order-ownership scoping is status-blind: removed the "whose status is `PROPOSED` or `CONFIRMED`" qualifier; any matching assignment row counts (COMPLETED/RELEASED included), leaving lifecycle enforcement to each endpoint's from-state gate — middleware.py:47-71 (judgment call 1).
2. §2.4 — insert — ambiguity — `version` starts at 1 at creation and `created_at` == `updated_at` at creation — services/store.py:5-7.
3. §2.7 — insert — ambiguity — on both OCC-protected writes the `ERR_ORDER_NOT_REGISTERED` 409 gate is evaluated before the `ERR_STALE_ORDER_VERSION` 412 check — routes/estimates.py:33-37, routes/estimates.py:161-165.
4. §2.10 stage 4 — insert — ambiguity — body-reference existence fires only for present, string-typed identifiers (absent/mistyped fall to stage 5); dispute filing is the exception where well-formedness and subject-shape rules precede subject resolution — util.py:164-170, routes/settlement.py:258-280 (judgment call 3).
5. §3.1 — insert — ambiguity — tariff cent rates are non-negative integers and `fuel_surcharge_pct` a non-negative decimal fraction (400 on violation) — routes/core.py:204-218.
6. §3.2 — revise — **mismatch** — assignment confirmation requires the caller's agent role to correspond to the assignment's `role` (not merely `agent_id` equality); also named `ERR_AGENT_SUSPENDED` for a since-suspended confirming assignee — routes/assignments.py:55-63.
7. §3.3 — insert — ambiguity — estimate-issuance check order pinned: REGISTERED gate → version check → kind match — routes/estimates.py:33-40.
8. §3.5 — insert — ambiguity — SIT release advances the order only when the order is currently `IN_SIT`; releasing another lot after the order already advanced leaves the order state unchanged — routes/transit.py:288-290.
9. §3.7 — revise — **mismatch** — delivery gate one admits `IN_SIT` when no lot remains `IN_STORAGE` (CONVERTED_PERMANENT lots neither block nor force OUT_FOR_DELIVERY), and the 180-day rule is re-evaluated on all the order's lots before the gates run — routes/orders.py:170-183 (judgment call 2).
10. §3.8 — insert — ambiguity — manual chargeback `amount_cents` must be at least 1 — routes/settlement.py:71-74.
11. §3.9 — insert — ambiguity — claim filing with no LOCKED coverage records null `valuation_coverage_id`, and the offer ceiling then equals the claimed amount; `offer_amount_cents` pinned non-negative — routes/settlement.py:120-128, 167-175.
12. §3.9 — insert — ambiguity — dispute-filing ordering note (400/422 before subject 404), `response_note` accepted but not persisted, and arbitration claim cascade guarded to claims still `FILED`/`DISPUTED`/`OFFER_MADE` while leaving the last negotiated `offer_amount_cents` untouched — routes/settlement.py:253-280, 333, 364-392; services/lifecycle.py:129-139 (judgment call 4).

**Judgment call 5** (PORT=10000 default, app.py:53): verified as INSTRUCTION.md-level deployment contract, not PRD-visible API behavior; deliberately not pinned.

