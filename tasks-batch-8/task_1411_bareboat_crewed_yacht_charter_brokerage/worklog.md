# Worklog — task_1411_bareboat_crewed_yacht_charter_brokerage

## Step 1: Create Task Directory — 2026-08-13T04:49:03.896Z

Task directory `tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invocation. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T06:01:20.818Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/`, generated purely from the scenario + skill spec (no sibling tasks consulted).

## Files written
- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys) — ~740 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts (from lint verdict)
- Entities: **14** (Operator, Broker, Client, Yacht, AvailabilityBlock, CharterRequest, CharterAgreement, EscrowAccount, EscrowMovement, ExpenseEntry, ItineraryLeg, PortPermit, InsuranceCertificate, CommissionStatement)
- State machines: **12** entries (9 entities; CharterAgreement carries two — `status` × `funds_status` parallel axes)
- Endpoints: **56** (incl. `POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z)
- Errors: **29** (all referenced and triggerable — verified programmatically)
- §1.8 instances: **21** (9 rules; combinatorial_formula has 3 — one per mode a/b/c; priority_pair has 3 distinct category pairs; cross_entity_state_dependency has 3 distinct entity pairs)
- §1.9 instances: **50** (44 active + 6 `excluded_because` stubs), 883 total calls lint-scanned

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```
Additionally verified offline: placeholder closure (zero unbound `${var}`), instance-name uniqueness across both design files, stub citations resolve, all numeric asserts pre-computed against the formulas (Python-checked), no forbidden race vocabulary, enum-value closure, trigger↔side-effect match.

## Notable design decisions (max-depth choices)
- **Archetype blend**: temporal windowing (primary) + ledger reconciliation (secondary); flat topology with a self-referential `CharterRequest.rebooked_from_request_id` (rebooking chain).
- **Dual-variant calcs on two domains**: quote pricing (PRO_RATA ÷7 vs WEEKLY_PLUS_DAILY ÷6 — the authentic industry ambiguity) and APA position (PROVISIONAL includes PENDING vs FINAL approved-only); a third variant pair on commission basis (CHARTER_FEE tiered vs CANCELLATION_PENALTY flat 20%).
- **Combinatorial formulas in all three modes**: cancellation penalty (tiered branch + nested `min(penalty, held_charter_fee)` cap), commission split (pinned rounding order: total → retail share → residual to central; fixture fee 666673 yields total 100001 → retail 50001 / central 50000, breaking naive independent rounding), funding schedule (circular-looking fee→tier→APA→tranches with pinned evaluation order; odd cent lands in the signing half).
- **Parallel state axes** on CharterAgreement (`status` × `funds_status`) with cross-axis gates; **cyclic** negotiation machine with round cap 4 and lazy offer expiry (deliberately *not* in the clock sweep so `ERR_OFFER_EXPIRED` stays reachable).
- **Two transitive cascades with causal hop chains**: cancellation (depth 6: agreement→funds→escrow movements→escrow CLOSED→funds REFUNDED→CHARTER block released→request CANCELLED) and completion settlement (depth 4, incl. auto-rejection of unresolved expenses before APA FINAL).
- **Two interval geometries**: half-open + 1-day turnaround buffer on yacht calendars (distinct errors for true overlap vs buffer adjacency) vs closed-interval containment on port permits; leg `PERMITTED` is a bubble-up derivation (≥1 GRANTED ∧ 0 REQUESTED; DENIED/EXPIRED don't block).
- **Segregation of duties**: `Broker.broker_type` ∈ {CENTRAL_AGENT, RETAIL_BROKER, BOTH} with a conflict-of-interest rule barring same-broker both-sides deals.
- **Three OCC rules** (counter, accept, manual block creation) all passing the serial-observability filter; every `expected_*_version` in recipes references captured versions or `${var} - 1` expressions.

## Step 3: Copy Shared Files — 2026-08-13T06:01:53.382Z

Copied `./INSTRUCTION.md` → `tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T06:03:00.000Z

PRD generation complete. Summary:

**Output written**: `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/workspace/PRD.md` — 320 lines.

**Section structure**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (11 subsections): 2.1 RBAC with per-role identity translations; 2.2 Response Structure (verified byte-identical to the canonical `section-2.2-response-structure.md`); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Common Resource Properties (incl. the `common_fields: false` carve-out — `EscrowMovement`/`CommissionStatement` carry only `id` + `created_at`); 2.5 Logical Clock (startup default 2026-08-01T00:00:00Z, permit-expiry sweep, lazy offer expiry); 2.6 Monetary Precision (integer cents, round half-up per pinned step); 2.7 Calendar semantics (half-open intervals, 1-day turnaround buffer); 2.8 Dual state axes (`status` × `funds_status` with the four gates); 2.9 Cascades/versioning/left-to-right path validation; 2.10 OCC (all 3 rules); 2.11 Validation Pipeline (8 priority tiers in order)
- §3 Business Logic (9 subsections, chronologically grouped): onboarding → listings/calendar → negotiation → acceptance snapshot → escrow funding → insurance/itinerary/permits → readiness/expenses/APA → completion settlement → cancellation/refund cascade
- §4 Endpoint table: all 56 endpoints, 4 columns only
- §5 Error catalogue: all 29 errors with correct HTTP statuses, 2 columns only

**Hard contracts** (all PASS, mechanically verified):
- Contract 1 field coverage: 75/75 entity fields, 47/47 request-body identifiers, 15/15 query params — 0 missing (one miss, `itinerary_leg_id`, found and repaired)
- Contract 2 rule coverage: 8 validation priority tiers expressed as ordered prose; 3/3 OCC rules with `expected_charter_request_version`/`expected_yacht_version` + `ERR_STALE_VERSION` (412); all 40+ state transitions across 12 state machines with preconditions, error ids, and side effects; all 7 calculations (quote variants, APA tier, APA position variants, funding schedule pinned order with odd-cent rule, penalty tiers with 60/59-day boundary, commission tiers with pinned rounding order, deposit settlement `min` cap); cross-entity cascades rendered hop-by-hop (acceptance 3-hop, completion 4-hop, cancellation 6-hop incl. `PENDING_SIGNATURES` empty-refund nuance and `IN_PREP` damage-claim pre-deduction); sibling asymmetry preserved (first offer checks operator standing, re-offer does not); all 29 error ids appear in §2/§3 prose
- Contract 3 path purity: 550 backticked tokens in §3 scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos

**Zero-Silence confirmation**: every §1.5 endpoint's preconditions and side effects are rendered as prose — including the clock sweep semantics (permits swept eagerly, offer expiry lazy), per-endpoint filter sets, the agreement-scoped escrow/block reads (0–1 arrays), movements in posted order, legs in `seq_no` order, and the tranche-sequencing-before-amount-check ordering on fund. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Steps 5+6: Generate Tests + Implementation (concurrent) — 2026-08-13T07:07:20.984Z

### Step 5 subagent summary (unit tests)

All done. Final summary:

## Deliverables

**`/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/test_helpers/`** — 9 files:
- `types.py` — status enums + TypedDicts for all 14 entities; `EscrowMovement`/`CommissionStatement` correctly carry only `id`+`created_at` (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (51 endpoints)
- `api_errors.py` — all 30 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity validators, `assert_escrow_closed_invariants`, `summarize_movements` aggregator
- `factories.py` — payload factories (input fields only); `constants.py` — PRD thresholds (tiers, caps, buffer, round limit)
- `test_users.py` — `TEST_USERS` + per-instance `make_*_headers` builders (Operator/Client/RetailBroker/CentralAgent are entity-backed; PlatformAdmin opaque)
- `fixtures.py` — composite deal builders: marketplace → listed yacht → submitted → offered → accepted → signed → fully-funded → in-prep → underway, plus insurance/permit/expense helpers; all setup via `get_success_data` with identity threading

**`.../test_suite/`** — `conftest.py` (session API client + fresh-connection-pool autouse fixture for per-test-server restarts) + 6 test files, **86 tests total** (42 queue-A + 44 queue-B). `pytest --collect-only` passes; all files compile.

## Coverage

- **Queue A (Difficulty): 21/21 instances translated, 2 tests each (42/42).** 0 skipped.
- **Queue B (Corner): 44/44 non-stub instances translated, 1 test each (44/44).** 0 skipped. All 7 `excluded_because:` stubs left untranslated; their `difficulty_instance` cross-references all resolve.

## PRD-first adjudication decisions (no instances skipped; four translations hardened)

1. **`retail_pct_bps` default is unstated in the PRD**, so every fixture offer pins `retail_pct_bps=5000` explicitly — making all asserted 50/50 share values (e.g. 50001/50000 residual split, 60000/60000 penalty split) uniquely derivable.
2. **Absolute version numbers** from recipes (e.g. "version == 4") were converted to relative +1-per-mutation assertions, since PRD §2.9 pins increments but not the initial value.
3. **`not_found_precedes_business_rules`** recipe called cancel as PlatformAdmin, but the §2.11 pipeline (role-check tier 2 before existence tier 3) would yield 403 — translated with a Client caller so §2.9's left-to-right rule uniquely pins 404.
4. **Offer-expiry timestamp** asserted as parsed instant (== 2026-08-08T00:00:00Z), not string equality, leaving ISO-8601 format freedom.

## Stage 2 self-check verdict

- Design tags: every test has exactly one `Design:` line resolving verbatim to a real instance (audit script: 86/86 pass, rule_id/section cross-checked).
- PRD citations: every quoted span ≥4 words verified to survive whitespace/markdown-normalized literal match against `PRD.md` (86/86 pass after normalizing the PRD's `**` bold markers and `§`/`section` spelling).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; all stub cross-references resolve. **PASS.**

### Step 6 subagent summary (implementation)

Implementation complete. Summary:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/workspace/implementation/`:

- `start.sh` — guarded dependency install (`import flask` check, no-op on per-test reboots) + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, `before_request` auth, envelope-shaped error handlers (404/405/500), blueprint registration
- `store.py` — in-memory dict store (14 collections, **empty at every boot, zero seeding**) + logical clock defaulting to exactly `2026-08-01T00:00:00Z`, `new_record`/`mutate` helpers (version starts at 1, +1 and updated_at refresh on every mutation per PRD §2.9)
- `util.py` — ISO-8601 3-fractional-digit timestamps, strict YYYY-MM-DD dates, Decimal ROUND_HALF_UP money math
- `httpkit.py` — exact scaffold envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), full 29-id error catalog with correct HTTP codes, `limit`/`offset` pagination (default 10, 1–100, `total_count`/`has_more`), auth (`X-User-ID`/`X-User-Role`, entity-backed identity + broker_type admittance), field validators
- `serializers.py` — per-entity public shapes (EscrowMovement/CommissionStatement slim: only id+created_at)
- `services.py` — all calculations (charter_fee_quote PRO_RATA/WEEKLY_PLUS_DAILY, APA tiers with 2,000,000 boundary → 0.25, funding schedule with odd-cent-to-signing rule, cancellation penalty tiers, commission tiers with pinned rounding order total→retail→central-residual, deposit settlement), half-open overlap vs 0-day turnaround buffer, duplicate guard, leg bubble-up roll-up, permit expiry sweep, and the accept / completion (4-hop) / cancellation (6-hop) / void cascades with positive-only ledger movements
- `routes_core.py`, `routes_yachts.py`, `routes_requests.py`, `routes_agreements.py`, `routes_expenses.py`, `routes_insurance.py`, `routes_itinerary.py`

## Endpoint count
**56 routes** — matches the SCAFFOLD §1.5 endpoint table exactly.

## Boot + behavior verification
Booted via `bash start.sh` three times (fresh process each); verified with curl:
- Full happy path: operator/broker/client onboarding → yacht create/list → request → submit → offer (PRO_RATA fee 700000; APA tier 0.30; WEEKLY_PLUS_DAILY 9-day quote 466666 = 350000 + 2×58333) → OCC-guarded accept (201, agreement snapshot with sign_due 550000 / final_due 640000, escrow OPEN, CHARTER block, yacht version bump) → insurance gate (422 pre-verify) → dual signatures (dup → 409) → tranche funding (order/amount 422s, correct bucket postings) → leg/permit flow → start-prep/embark gates → completion cascade: COMPLETED/SETTLED, escrow CLOSED with funded == released == 1190000, statement 105000/42000/63000
- Cancellation cascade at 110 days → 10% tier, penalty 15000, penalty-commission 3000 split 1500/1500, escrow balanced and CLOSED, CHARTER block RELEASED, request CANCELLED; void flow releases block + cancels request
- Edge gates all confirmed: ERR_STALE_VERSION (412), ERR_OFFER_EXPIRED with lazy EXPIRED transition, ERR_NEGOTIATION_ROUND_LIMIT at 4, ERR_AVAILABILITY_CONFLICT vs ERR_TURNAROUND_BUFFER_VIOLATION (1-day gap passes), ERR_BROKER_CONFLICT_OF_INTEREST, ERR_CAPACITY_EXCEEDED, ERR_CHARTER_DURATION_INVALID, ERR_DUPLICATE_ACTIVE_REQUEST (3 enforcement points), ERR_CLIENT_NOT_QUALIFIED, ERR_OPERATOR_SUSPENDED, ERR_INSURANCE_*, ERR_PERMIT_WINDOW_INSUFFICIENT, permit expiry sweep flipping legs PERMITTED→PLANNED, 401/403/404 auth pipeline
- Fresh reboot confirmed: empty store (`total_count: 0`), clock back at default — clean per-test-server restart semantics

One deliberate PRD-literal choice worth noting: `listing_central_agent_id` on yacht creation must reference a broker with `broker_type == CENTRAL_AGENT` strictly (BOTH rejected with ERR_INVALID_REQUEST), per the explicit wording in both PRD §3.2 and the scaffold entity table; segregation-of-duties at request creation is reachable via a client-supplied `retail_broker_id` equal to the listing central agent.

## Step 7: Test/Fix Iteration Loop — 2026-08-13

### Iteration 1 sweep (baseline)
8 parallel rounds, per-test-server isolation. All 8 rounds: 83/86 passed. Union of failures (consistent across all 8 rounds, no flakiness):
1. `test_01::test_broker_conflict_of_interest_rejected` — setup 400: yacht creation rejected a `BOTH` broker as `listing_central_agent_id`.
2. `test_04::test_funds_axis_advances_independently_of_status` — setup 422 `ERR_INSURANCE_NOT_VERIFIED`: test signed without filing insurance.
3. `test_06::test_cancel_in_prep_deducts_approved_damage_claims` — `KeyError ('RELEASE_TO_CENTRAL_AGENT','CHARTER_FEE')`: 11th escrow movement truncated by the default page size (limit=10).

### Diagnoses + fixes
1. TEST FAITHFUL / IMPLEMENTATION BUG — PRD §3.1 ("A BOTH broker may wear either hat across the marketplace") + §3.3 ("This is where a BOTH broker is stopped from standing on both sides of one deal") presuppose BOTH brokers can hold listings; the strict §3.2 reading would vacate both sentences. Fix: `implementation/routes_yachts.py::create_yacht` admits `broker_type in (CENTRAL_AGENT, BOTH)` (RETAIL_BROKER-only still rejected).
2. TEST BUG (test_suite) — PRD §3.4 verbatim: "Signing requires a VERIFIED insurance certificate on the agreement — without one the attempt is rejected with ERR_INSURANCE_NOT_VERIFIED." The test signed with no certificate. Fix: `test_suite/test_04_agreements_signing_funding.py` — added `file_verified_insurance(...)` before the first signature (certificate create/verify does not mutate the agreement, so the `version == ag.version + 2` assertion still holds).
3. TEST BUG (test_helpers) — PRD §2.3 pins default limit=10; settlement scenarios post 11-12 movements (4 funding + 7-8 cascade), so the fixture silently dropped the 11th. Fix: `test_helpers/fixtures.py::list_movements` now defaults `limit=100` (the PRD maximum), overridable per call.

### Iteration 2 sweep (post-fix)
8/8 rounds: 86/86 passed, 0 failed, 0 errors. CLEAN SWEEP — exit condition met.

No tests deleted. No assertions weakened. No implementation capability added beyond PRD prose; storage remains in-memory only with zero seeding.

### Step 7 subagent exit summary (verbatim, recorded by orchestrator) — 2026-08-13T07:20:05.771Z

Clean sweep achieved. Final summary:

## Summary

**Iterations run:** 2 (baseline sweep → 3 fixes → verification sweep)

**Result:** All 8 parallel rounds pass 86/86 tests, 0 failed, 0 errors. Exit condition met.

**Tests deleted:** None. Every failing test traced to verbatim PRD prose; no PRD-silence or unique-derivability deletions were warranted.

**Baseline failures (identical in all 8 rounds — no flakiness):**

1. `test_01_clients_and_resume.py::test_broker_conflict_of_interest_rejected` — setup failed with 400 because yacht creation rejected a `BOTH`-type broker as `listing_central_agent_id`.
2. `test_04_agreements_signing_funding.py::test_funds_axis_advances_independently_of_status` — setup failed with 422 `ERR_INSURANCE_NOT_VERIFIED` because the test signed an agreement without filing insurance.
3. `test_06_settlement_cancellation_commissions.py::test_cancel_in_prep_deducts_approved_damage_claims` — `KeyError ('RELEASE_TO_CENTRAL_AGENT','CHARTER_FEE')`: the 11th escrow movement was truncated by the PRD-default page size of 10.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/test_helpers/fixtures.py` — `list_movements` fixture: default `limit=100` (PRD §2.3's maximum) so settlement scenarios posting 11-12 movements (4 funding + 7-8 cascade) aren't silently truncated at the default page of 10.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/test_suite/test_04_agreements_signing_funding.py` — `test_funds_axis_advances_independently_of_status`: added `file_verified_insurance(...)` before the first signature. PRD §3.4 verbatim requires a VERIFIED certificate before any signature ("without one the attempt is rejected with `ERR_INSURANCE_NOT_VERIFIED`"); the test's setup omitted it. Insurance create/verify mutates only the certificate, so the existing `version == ag["version"] + 2` assertion still holds.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/workspace/implementation/routes_yachts.py` — `create_yacht`: admit `broker_type in ("CENTRAL_AGENT", "BOTH")` for `listing_central_agent_id` (RETAIL_BROKER-only still rejected with `ERR_INVALID_REQUEST`). Rationale: §3.1 ("A `BOTH` broker may wear either hat across the marketplace") and §3.3 ("This is where a `BOTH` broker is stopped from standing on both sides of one deal") both presuppose a BOTH broker can hold a listing; the strict reading of §3.2's "must reference a broker whose `broker_type` is `CENTRAL_AGENT`" would render both sentences vacuous, so the whole-document reading uniquely determines admittance. No PRD-required check was weakened — the conflict-of-interest gate itself is untouched and is exactly what the test asserts.

## Step 8: Finalize PRD — 2026-08-13T07:27:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/workspace/PRD_FINALIZED.md` written.

## Summary

**Line counts:** PRD.md = 320 lines, PRD_FINALIZED.md = 320 lines (0% line-count delta; 1 line modified in place).

### Changes (one edit total)

- **§3.2 — revise —** `listing_central_agent_id` admittance widened from "`broker_type` is `CENTRAL_AGENT`" to "`broker_type` is `CENTRAL_AGENT` or `BOTH`", with an added parenthetical pinning that a `RETAIL_BROKER`-only broker is rejected with `ERR_INVALID_REQUEST`. The conflict-of-interest gate (§3.3, same broker on both sides of one deal) is untouched and remains intact. — `implementation/routes_yachts.py:52-66`

### Step-7 items requiring no PRD edit

- `test_helpers/fixtures.py` `list_movements` limit=100 — pure fixture fix; PRD §2.3 already pins default 10 / max 100.
- `test_suite/test_04` adding `file_verified_insurance(...)` before signing — test-side fix; PRD §3.4 already verbatim requires a VERIFIED certificate (`ERR_INSURANCE_NOT_VERIFIED`) before any signature.

### Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit 1 (§3.2 admittance clause):**
- (a) **Subject:** which `broker_type` values qualify a broker referenced by `listing_central_agent_id` at yacht creation.
- (b) **Impl paths enumerated and read/grepped:**
  - `implementation/routes_yachts.py:52-66` — the Step 7 site: existence check (`ERR_NOT_FOUND`), then `broker_type not in ("CENTRAL_AGENT", "BOTH")` → `ERR_INVALID_REQUEST`.
  - `implementation/routes_requests.py:101-111` — conflict-of-interest gate: pure id-equality against `listing_central_agent_id`, type-agnostic; §3.3 wording stays valid for a BOTH listing agent.
  - `implementation/routes_requests.py:191-208` — offer endpoint: caller id must equal `listing_central_agent_id`; role admittance (`httpkit.py:195-202`) lets a BOTH broker act as `CentralAgent`, so "will hold the listing and issue offers" remains true.
  - `implementation/services.py:287` — agreement snapshot copies `central_agent_id` from the yacht with no type re-check.
  - `implementation/routes_agreements.py:28-29, 152-161, 185-187, 314-341` — sign/void/complete/cancel compare `central_agent_id` by id only.
  - `implementation/routes_core.py:84`, `implementation/httpkit.py:195-202` — broker creation / role admittance; already verbatim-covered by PRD §2.1 and §3.1.
  - PRD cross-reference grep: §2.1 (line 17), §3.1 (line 143), §3.3 (line 159) — all already consistent with BOTH admittance; no other PRD sentence needed reconciliation.
- (c) **Wording adjustment:** added the `ERR_INVALID_REQUEST` parenthetical for a `RETAIL_BROKER`-only broker (behavior the impl exhibits at routes_yachts.py:62-66, contradicted by no enumerated path); deliberately avoided pinning a validation-pipeline tier or check ordering, since the impl's ordering (field parse → FK existence → type check) is not PRD-determined and claiming one would risk a new mismatch.

## Step 9: PRD Completeness Scan — 2026-08-13T07:35:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1411_bareboat_crewed_yacht_charter_brokerage/workspace/PRD_COMPLETED.md` written.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` 320 lines / 58,679 chars → `PRD_COMPLETED.md` 320 lines / 60,658 chars (char-delta +1,979; 13 paragraphs touched, all inline inserts — no new sections, no reformatting).

**Counts:** 13 ambiguity-pins, 0 mismatch-revisions. Implementation was exhaustively walked (`app.py`, `httpkit.py`, `store.py`, `util.py`, `services.py`, all 7 route modules, `serializers.py`); every formula, state transition, check order, default, and serializer field already matched PRD prose — only silent implementation choices needed pinning.

**Changes (all insert / ambiguity):**

- §2.2 — insert — ambiguity — success envelope now states a computed read-only view (APA position) returns a plain fields object and the clock endpoint returns `current_utc` — implementation/routes_agreements.py:114, routes_core.py:34
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (outside 1–100) and negative/non-integer `offset` rejected with `ERR_INVALID_REQUEST` — implementation/httpkit.py:109-134
- §2.4 — insert — ambiguity — `version` starts at 1 on creation (was "its initial value") — implementation/store.py:61
- §2.5 — insert — ambiguity — unparseable `to_iso8601` rejected with `ERR_INVALID_REQUEST` — implementation/routes_core.py:28-31
- §2.6 — insert — ambiguity — `apa_pct` pinned as a JSON number (impl stores `float(pct)`, e.g. 0.3) — implementation/services.py:532
- §3.1 — insert — ambiguity — `skippered_hours` pinned as a non-negative integer — implementation/routes_core.py:140
- §3.2 — insert — ambiguity — listing numerics pinned: `capacity_berths`/`weekly_base_rate_cents`/`min_charter_days` positive ints, `security_deposit_cents` non-negative — implementation/routes_yachts.py:38-48
- §3.3 — insert — ambiguity — request creation does not require the yacht to be `LISTED` (the `ERR_YACHT_NOT_LISTED` gate is submission-only) — implementation/routes_requests.py:80-137
- §3.3 — insert — ambiguity — offer overrides validated: `apa_pct` non-negative number; omitted `gratuity_pledged_cents`/`retail_pct_bps` lock at 0; `retail_pct_bps` must be an integer in [0, 10000] — implementation/routes_requests.py:215-228, services.py:525-526
- §3.3 — insert — ambiguity — `counter_charter_fee_cents`, when supplied, must be a positive integer — implementation/routes_requests.py:258-259
- §3.3 — insert — ambiguity — acceptance clears `offer_expires_at` to null (only counter previously documented as clearing it) — implementation/services.py:267-335 (accept_cascade never carries it; `ACCEPTED` requests read null)
- §3.3 — insert — ambiguity — rebook's exact check set pinned: date order, guests ≥ 1, existence of `yacht_id` (and `retail_broker_id` for client callers), duplicate guard; capacity, min-duration, segregation-of-duties, calendar, and listing checks are not re-run — implementation/routes_requests.py:295-327
- §3.5 — insert — ambiguity — cascade steps whose computed amount is zero post no movement (ledger never holds zero-amount entries) — implementation/services.py:223-224

Everything else — calendar rules, OCC guards, validation-pipeline tiers and same-tier check orders, quote/APA/commission/penalty formulas with pinned rounding order, funding tranche sequencing, both cascades hop-by-hop, leg roll-up, clock sweep, all endpoint/role/filter/ordering specs — verified as already uniquely pinned by the PRD.
