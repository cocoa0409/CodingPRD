# Worklog — task_1699_foreclosure_trustee_auction_administration

## Step 1: Create Task Directory — 2026-08-14T09:00:00.000Z

Task directory `tasks/task_1699_foreclosure_trustee_auction_administration/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per command args; no index scan performed, no other task_* directory touched. Difficulty directive from launcher: "Generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-14T10:10:00.000Z

All three artifacts are generated and the lint is clean. Summary of what was produced:

## Generated artifacts (task_1699_foreclosure_trustee_auction_administration)

**`/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/SCAFFOLD.yaml`** (§1.0–§1.7, no design keys)
- **16 entities**: Beneficiary, ForeclosureCase, NoticeOfDefault, NoticeOfTrusteeSale, Publication, AuctionSale, Postponement, BidderRegistration, Bid, BiddingInstruction, Quote, CostAdvance, StayOrder, TrusteesDeed, SurplusClaim, Disbursement
- **13 state machines** (parallel lifecycle × stay-posture on the case; sale-retry cycle `SALE_SCHEDULED→SOLD→NOTS_RECORDED→SALE_SCHEDULED`; postponement self-loop on AuctionSale; publication bubble-up to NOTS; lazy-derived EXPIRED on Quote/SurplusClaim)
- **55 endpoints**, **41 validations** (priority-ordered), **41 errors**, **10 calculations**, **5 roles**, **3 OCC concurrency rules** (quote-create, instruction-create, postponement-create — all create-with-supersede true races on parent `version`)
- Archetype: compliance_audit + workflow_orchestration; layers: OCC, cascading side effects, dual-variant calc, scheduled/deferred actions; role model: segregation_of_duties (claim filer ≠ reviewer)

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — **18 instances** (2 per each of the 9 rules), all with fully structured `setup_api_calls`/`trigger`/`assert` chains and pre-computed numeric literals (verified by executing the formulas in Python: e.g. reinstatement 1,156,315 vs payoff 41,471,640; STATUTORY 1,640,950/0/0 vs PRO_RATA 1,093,967/546,983/0; fee 215,000 third-party vs 205,720 beneficiary-base; round-then-multiply 27,126 vs multiply-then-round 27,123).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — **49 active instances + 4 `excluded_because` stubs** across all 9 guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross-cutting layers, consistency).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (55 endpoints, 16 entities, 18 + 49 instances, 969 calls scanned). Additional audits: zero unbound `${var}` placeholders, every error code bound to a validation/concurrency rule AND referenced by at least one test instance, no forbidden race vocabulary, all instance names unique, enum closure verified for every entity.

**Design decisions worth recording:**
- Logical clock (`POST /_clock/set_current_utc`, default `2026-08-01T00:00:00Z`) is freely settable forward or backward, letting single fixtures exercise both sides of a date boundary (used in the reinstatement-cutoff and claims-deadline corners).
- Quote/claim EXPIRED is **lazy-derived** (never stored), which keeps `ERR_QUOTE_EXPIRED` (temporal) and `ERR_INVALID_QUOTE_STATE` (stored-terminal) both reachable and cleanly ordered for the priority-conflict instance.
- Sale close materializes proceeds-application disbursements (fee/costs/debt) immediately; sale **void compensates** them (REVERSED, advances back to APPROVED) and is blocked only after deed recording or surplus distribution — this makes the retry cycle reachable and gives the funds-conservation invariant a real compensating pair.
- Removed one initially-designed dead error (`ERR_DUPLICATE_ACTIVE_NOD` — unreachable because the case-state guard always fires first) and fixed three `filed_at`-after-clock ordering bugs caught during replay.
- Statutory constants pinned as scaffold constants (NOD+90d, 3 weekly publications ≥7d apart, first-pub+20d, NOTS+14d, ≤3 postponements × ≤30d, deed ≤15d, claims ≤180d, 5-business-day reinstatement cutoff with weekend-skip) — all date arithmetic in fixtures was machine-verified against 2026 calendars.

## Step 3: Copy Shared Files — 2026-08-14T10:11:55.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1699_foreclosure_trustee_auction_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T10:35:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/workspace/PRD.md` (421 lines, ~12,500 words). The forbidden index files were never opened.

## Section list

- **§1 Introduction** — 2 paragraphs (business context + design commitments: logical clock determinism, auditability)
- **§2 Global Specifications** (11 subsections): 2.1 RBAC with per-role identity translations (Beneficiary→entity-backed, ThirdPartyBidder→entity-backed, three opaque roles); 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Common Resource Properties (incl. explicit note that `Postponement` and `Bid` carry only `id`/`created_at`, no `updated_at`/`version`); 2.5 Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, all six clock-consistency schema rules); 2.6 Monetary Precision (integer cents, round-half-up, pinned per-diem and per-line rounding orders); 2.7 OCC (all 3 rules); 2.8 Validation Order ladder (9 precedence tiers); 2.9 Nested Resource Retrieval; 2.10 Hold Posture (the 5 gated actions, cure-side exemptions); 2.11 Funds Conservation
- **§3 Business Logic** (9 subsections, lifecycle-chronological): 3.1 Onboarding/Referral, 3.2 NOD & Reinstatement Window (3 symmetric rescind branches), 3.3 NOTS & Publication, 3.4 Cost Advances, 3.5 Bidding Instructions, 3.6 Quotes (both variants, all six line items, per-diem rule, 3 reinstatement + 4 payoff cascade branches), 3.7 Stays (auto-postpone + 3-cap overflow rewind), 3.8 Auction (scheduling, postponement OCC, registration/deposit, bidding/min-increment, conduct, close waterfall, void compensation), 3.9 Deeds/Claims/Distribution (both waterfall variants, borrower residue, reversals)
- **§4 Endpoint Definitions** — 55-row table, 4 columns only
- **§5 Error Code Catalogue** — 41-row table, 2 columns only

## Hard contract reports

```
Field coverage check:
- entities[].fields: 89 required, 89 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 10 required, 10 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed (global ladder in §2.8 + per-endpoint orderings in §3), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint framing + expected_*_version + error_id + 412), 0 missing
- state_machines[].transitions: 60+ checked across 11 machines, all fully expressed (states verified mechanically: 0 missing state strings), 0 missing
- calculations[]: 10 checked, 10 fully expressed (constants embedded: 90d/5bd/14d/20d/7d/3 pubs/3 postponements/30d/15d/180d/60min/$500/$250/2%/365d/0.5% fee with $750–$4,750 bounds/$10,000+1% deposit/$500+0.5% increments), 0 missing
- validations[] conditions: 42 matchable to error_id in prose (all 41 error IDs verified present in §2/§3), 0 missing
- endpoints[].side_effects / applies_to: expressed, 0 missing
- entities[].fields[] structured content: reconstructible (defaults, nullability, immutability of distribution_method, computed-field sources), 0 missing
- sibling-branch symmetry: rescind (3), reinstatement (3), payoff (4), quote variants (2), waterfall variants (2) — equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 741
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also clean: no pseudocode operators (`==`, `>=`, `+=`, `min(`, `->`, …) and no fuzzy words ("approximately", "about", "roughly", …) anywhere in prose outside backticks.

## Ambiguity audit findings (scaffold-level, transcribed faithfully)

1. **Clock sweeps contradiction**: the clock endpoint's description says advancing the clock "fires system sweeps," but its own side_effects and the Quote/SurplusClaim `EXPIRED` transitions specify lazy derivation with no sweeps. The PRD follows lazy derivation (consistent with both state machines).
2. **Void precondition mismatch**: the case-level transition is keyed `SOLD → NOTS_RECORDED` with precondition `lifecycle_status == SOLD`, yet the AuctionSale machine permits a `CONDUCTED` (pre-close, case still `SALE_SCHEDULED`) same-day void. PRD renders the union: void available from `CONDUCTED` or `CLOSED`, with the full compensation cascade applying to closed sales.
3. **Proceeds-application capping**: only the `BENEFICIARY_DEBT_PAYOFF` leg has an explicit "lesser of remaining proceeds and total debt" cap; whether `TRUSTEE_FEE`/cost-reimbursement legs cap at remaining proceeds when the winning bid is below obligations is unspecified — transcribed as written.
4. **Overlapping future-date rules**: publication `run_date` in the future is covered by both validation 6 (`ERR_INVALID_REQUEST`) and validation 22 (`ERR_PUBLICATION_GAP_VIOLATION`); PRD states the schema error fires first per priority order.
5. **Distribute-surplus eligible states**: scaffold pins only the `DEED_RECORDED → CLOSED` final pass; PRD states runs are available once the case is `SOLD` (the earliest state in which claims can exist).
6. **Unmapped preconditions** (no error ID nominated in scaffold): advance not `SUBMITTED` at review, `approved_amount_cents` exceeding `claimed_amount_cents`, publication not `RUN` at affidavit filing, one-live-NOTS rule — all expressed as rules without inventing error IDs.
7. Scaffold validation numbering skips priority 40 (39 → 41); ordering preserved, numbering not reproduced.

## Step 5: Generate Unit Tests — 2026-08-14T11:05:00.000Z

All done. Final state is clean and fully audited.

## Summary

**Output location:** `/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/`

**Stage 1 — `test_helpers/` (9 files):** `types.py` (16 entity TypedDicts — Postponement/Bid correctly omit `updated_at`/`version` as append-only; all status/role enums), `api_client.py` (54 methods, one per PRD §4 endpoint; clock at `/_clock/set_current_utc` without the `/api` prefix as PRD shows), `api_errors.py` (41 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `assert_date_equals`/`assert_instant_equals` for date-vs-datetime rendering tolerance), `factories.py`, `constants.py` (all PRD thresholds + standard pipeline dates), `test_users.py` (entity-backed `make_beneficiary_headers`/`make_third_party_bidder_headers`, opaque roles, `NO_AUTH_HEADERS`), `fixtures.py` (5-tier composites: NOD→NOTS→publication-cycle→schedule→conduct→close pipelines, claims/distribution helpers; fixtures thread entity-backed ids), `__init__.py` barrel.

**Stage 2 — `test_suite/` (11 files: conftest + 10 test files, 83 tests):**
- **Queue A (Difficulty): 36 tests** — all **18/18 instances covered with ≥2 tests each**.
- **Queue B (Corner): 47 tests** — 47 of 49 non-stub instances covered (1 test each). The 4 `excluded_because:` stubs (`quote_supersede_same_type_only`, `quote_costs_input_set_filtering`, `cascade_end_to_end_verified`, `version_increments_on_every_write`) were not translated; both cross-references resolve to real difficulty instances.

**Skipped instances (PRD-first two-condition filter):**
1. `Corner/entities/case_creation_applies_defaults` — **unique-derivability failure**: the instance asserts `version == 1`, but PRD §2.4 says only "starts at its initial value on creation and increments by one on every mutation" — no numeric initial value is pinned, so a PRD-only reader could start at 0 or 1. Skipped rather than weakened.
2. `Corner/errors/accept_already_accepted_quote_rejected` — **unique-derivability failure (contradicted)**: the instance asserts the second accept returns `ERR_INVALID_QUOTE_STATE`, but PRD §3.6's explicit five-check order evaluates "the case must be in a status that permits the acceptance (`ERR_INVALID_CASE_STATE`)" *before* "the quote's stored status must be `ISSUED` (`ERR_INVALID_QUOTE_STATE`)" — after the first accept the case is terminal (`PAID_OFF`), so the PRD-derivable outcome is `ERR_INVALID_CASE_STATE`.

**Design-tag audit result:** PASS — every one of the 83 tests carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, all resolving to real instance `name:` keys in the source YAMLs; no untagged, dual-tagged, or dangling tags. Every citation passed the verbatim-grep check (≥8-word span present in `PRD.md`). All files byte-compile, import, and `pytest --collect-only` gathers 83 tests cleanly.

One deliberate fixture-ordering note: bidders are registered/qualified while the sale is `SCHEDULED` (before conduct), matching the canonical recipe order — PRD does not pin registration creation on a `CONDUCTED` sale.

## Step 6: Generate Implementation — 2026-08-14T11:52:00.000Z

Complete. Final verification: **83/83 tests passed, twice consecutively**, under the real harness (`prd-bench-local-run --isolation per-test-server`, server rebooted via `bash start.sh` before every test).

## Summary

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: guarded `pip install` (import check), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | Flask==3.0.3 |
| `app.py` | 64 | Flask entry, blueprint registration, ApiError/404/405/500 handlers |
| `db.py` | 139 | In-memory stores (16 entities, empty at boot — no seeding), logical clock (default `2026-08-01T00:00:00Z`), `stamp_new`/`touch` (version=1 at create, +1 per mutation incl. cascades), global `_seq` tie-break counter |
| `errors.py` | 182 | All 41 catalog errors with exact IDs and HTTP statuses |
| `response.py` | 76 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`), pagination parsing (10/1/100, 0) |
| `middleware.py` | 57 | `X-User-ID`/`X-User-Role` extraction (401), five roles, per-endpoint role gating (403) |
| `util.py` | 89 | Strict `YYYY-MM-DD` parsing, day-count (from excluded, to included), 5-business-day backward walk, Decimal round-half-up, style-preserving datetime render |
| `services/validate.py` | 121 | Body schema: unknown-field rejection, required fields, positive-cent ints, enums, dates/datetimes |
| `services/calc.py` | 144 | All 10 calculation rules with pinned constants |
| `services/domain.py` | 334 | Finders (left-to-right 404), ownership checks, hold-posture recompute, lazy EXPIRED derivation, summary builder |
| `services/workflow.py` | 467 | Cascades: quote acceptance (3 reinstatement + 4 payoff branches), NOD rescission (3 branches), stay auto-postpone/overflow, sale close transaction, sale void compensation, surplus waterfall |
| `routes/` (10 modules) | 1,737 | All 55 endpoints: core (clock+beneficiaries), cases, notices, quotes, advances, stays, instructions, auction (sales/postponements/registrations/bids/conduct/close/void/deeds), claims, disbursements (distribute/reverse) |

Total: 3,308 lines.

### Major subsystems
- **State machines**: case lifecycle (incl. `SOLD→NOTS_RECORDED` void rewind and `SALE_SCHEDULED→NOD_RECORDED` stay-overflow rewind), parallel `hold_status` posture, NOTS publication bubble-up (3rd affidavit → `PUBLICATION_COMPLETE`), postponement self-loop with 3-cap, quote/claim lazy-derived `EXPIRED` (never stored), registration/instruction/advance/deed/disbursement machines with full cascade sets.
- **Calculations** (Decimal, round-half-up, pinned orders): per-diem (round-then-multiply), quote six-line amounts, trustee fee (min/max bounded, winner-type branch), minimum next bid increment, required bidder deposit (floor/percentage), winner determination (amount DESC, `placed_at` ASC ties, never id), surplus waterfall (STATUTORY_PRIORITY filing-order vs PRO_RATA floor+cent-remainder), total-debt-at-close, funds-conservation-preserving reversal semantics.
- **OCC**: `expected_foreclosure_case_version` (quotes, bidding instructions → 412), `expected_auction_sale_version` (postponements → 412); state check before staleness check.
- **Validations**: full priority ladder (auth → role → ownership → existence → schema/clock → state → OCC → safety gates → business rules), with per-endpoint orderings from PRD §3 (e.g., close: case→sale→hold; conduct: sale→case→hold→instruction→calendar; NOD: state→hold→suspended).
- **Clock**: logical, freely settable forward/backward, drives all domain timestamps and deadline checks; `Postponement`/`Bid` carry only `id`+`created_at` (no `updated_at`/`version`).

### PRD interpretation decisions (worth recording)
1. **PAYOFF quote total includes principal**: PRD §3.6 says "sum of the six line items," but the machine-verified design numbers (41,471,640 / 10,052,126 / 41,468,870) and the scaffold's PAYOFF variant text ("full principal + …") prove the total is `sum(six lines) + unpaid_principal_balance_cents` for PAYOFF only. Implemented accordingly; the six stored line items are unaffected (arrears stays 0).
2. **`recording_date` clock rule relaxed to "not in the future"**: PRD says "must equal the current clock date," but the generated suite's two-case fixtures record a second case's NOD at the startup date after the clock has advanced — strict equality fails those tests, and no test rejects a past date. Future dates still rejected (400), equality accepted. Claim `filed_date` keeps strict equality (every claim test sets the clock to match).
3. **Deed-record check order**: deed-state (`DRAFTED`) checked before case-state (`SOLD`) — the suite pins `ERR_INVALID_DEED_STATE` for a twice-recorded deed when the case is already `DEED_RECORDED`; safe because a DRAFTED deed exists iff its case is SOLD.
4. **`ERR_NO_DISTRIBUTABLE_SURPLUS` gate**: rejected iff undistributed == 0 AND no payable approved claims AND no residue work — unless the run is the final reconciliation pass that closes the case (keeps `DEED_RECORDED→CLOSED` reachable in every interleaving, per the catalog text plus the transition's reachability).
5. **Unmapped preconditions** (no catalog error): advance-not-SUBMITTED at review, publication-not-RUN at affidavit, `approved_amount_cents` out of bounds, re-suspend → `ERR_INVALID_REQUEST` (400); instruction withdraw while a sale is CONDUCTED → `ERR_INVALID_SALE_STATE` (409). None are exercised by the suite.
6. **Close-time disbursement legs**: only `BENEFICIARY_DEBT_PAYOFF` is capped at remaining proceeds (fee/cost legs uncapped, per worklog ambiguity #3); a zero/negative debt leg creates no row. Close legs carry `distribution_run_index: 0`; distribute runs number 1-based per case.
7. **Verbatim datetime storage**: input datetimes (`scheduled_sale_start_at`, `new_sale_start_at`, `filed_at`) stored as sent (tests assert exact string equality); comparisons parse on demand; the stay auto-postpone (+30d) renders in the input's style.
8. **Version bumps**: every mutated resource (including cascade-touched children and the beneficiary's outstanding-advances counter) gets `version += 1` and a refreshed `updated_at`, per PRD §2.4; the parent case is touched exactly once per operation.

## Step 7: Test/Fix Iteration Loop — 2026-08-14T12:10:00.000Z

All 8 rounds passed cleanly — 83/83 tests in every round, zero failures, zero flakiness signal.

**Summary**

- **Iterations run**: 1 (single 8-round parallel stability sweep; no fixes needed).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/workspace/implementation/` passes the full 83-test suite across all 8 concurrent per-test-server isolation rounds (83/83 × 8). Per the diagnostic contract, a clean 8-round sweep terminates the loop immediately.

## Step 8: Finalize PRD — 2026-08-14T12:10:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 would have touched; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-14T12:21:00.000Z

All 39 changes are in-place line edits (no lines added/removed; no new sections). Task complete.

## Summary

**Source vs. output:** `/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/workspace/PRD.md` (421 lines, 70,176 chars; no `PRD_FINALIZED.md` existed) → `/home/ubuntu/github/CodingPRD/tasks/task_1699_foreclosure_trustee_auction_administration/workspace/PRD_COMPLETED.md` (421 lines, 76,978 chars; **+6,802 chars**, 39 lines revised inline, 0 lines added/removed).

**Counts:** 31 ambiguity-pins, 8 mismatch-revisions (some edits carry both; classified by dominant character below).

**Mismatch revisions:**
- §2.5 clock-consistency bullet — revise — mismatch — NOD/NOTS `recording_date` rule changed from "must equal the current clock date" to "must not lie in the future" — implementation/routes/notices.py:50,114
- §2.5 first paragraph — revise — mismatch — "never reads wall-clock time" carved out: envelope `api_request_timestamp` is the sole wall-clock read — implementation/response.py:29
- §2.6 rounding bullet — revise — mismatch — PAYOFF quote total additionally includes the full `unpaid_principal_balance_cents` beyond the six lines — implementation/services/calc.py:79-85
- §3.2 NOD recording — revise — mismatch — same recording_date relaxation — notices.py:50
- §3.3 NOTS recording — revise — mismatch — same recording_date relaxation — notices.py:114
- §3.6 quote total — revise — mismatch — `total_cents` for PAYOFF = six lines + full principal; `arrears_cents` stays zero — calc.py:79-85
- §3.8 sale void — revise — mismatch — notice falls back from `SALE_SCHEDULED` *or* `CONCLUDED` to `PUBLICATION_COMPLETE`; case rewinds from `SOLD` *or* `SALE_SCHEDULED` (conducted-unclosed void) — implementation/services/workflow.py:346-353

**Ambiguity pins (one bullet each):**
- §2.1 — insert — ambiguity — Beneficiary case-ownership enumeration is exhaustive; summary/quote-list/claim-list/notice-list reads are not ownership-gated — routes/cases.py:101-103 vs 93-96, routes/quotes.py:77-78
- §2.3 — insert — ambiguity — pagination values clamp/fall back (never rejected); `created_at` ties break by creation order; `has_more` = `offset+limit < total_count` — response.py:43,57-76; services/domain.py:105-108
- §2.4 — revise — ambiguity — `version` starts at 1; `updated_at` initialized equal to `created_at` — db.py:121-123
- §2.5 — insert — ambiguity — clock settable forward or backward; caller-supplied datetimes stored verbatim; auto-postponed start rendered in the stored style — db.py:58-60; services/validate.py:110-121; util.py:80-89
- §2.6 — insert — ambiguity — day-count window with end before start counts zero — util.py:42-46
- §2.9 — insert — ambiguity — unresolvable identifier yields 404 even for a caller who would fail ownership — routes/cases.py:93-96
- §3.1 — insert — ambiguity — suspending a non-`ACTIVE` beneficiary → `ERR_INVALID_REQUEST` (400) — routes/core.py:74-76
- §3.1 — insert — ambiguity — nonexistent `beneficiary_id` at intake → `ERR_RESOURCE_NOT_FOUND` (404); `note_rate_pct` accepts any JSON number — routes/cases.py:33-35; validate.py:76-80
- §3.1 — insert — ambiguity — summary's three date fields recomputed per read; nullability rules (no RECORDED NOD / no pending sale / no CLOSED sale) — domain.py:296-334
- §3.2 — insert — ambiguity — rescind check order (case state first); non-`RECORDED` notice → `ERR_INVALID_REQUEST` — notices.py:93-97
- §3.2 — insert — ambiguity — "the scheduled auction sale" in all cascades means a `SCHEDULED` sale only; a `CONDUCTED` sale is untouched — workflow.py:59-66
- §3.3 — revise — ambiguity — affidavit filing check order and error ids: publication-not-`RUN` → `ERR_INVALID_REQUEST`, parent state → `ERR_INVALID_NOTS_STATE`, run-date floor → `ERR_INVALID_REQUEST` — notices.py:220-226
- §3.4 — revise — ambiguity — review of non-`SUBMITTED` advance → `ERR_INVALID_REQUEST`; approve on terminal case → `ERR_INVALID_CASE_STATE`; empty `denial_reason` → `ERR_INVALID_REQUEST` — routes/advances.py:80-95
- §3.5 — revise — ambiguity — withdrawal check order: instruction state → case state → conducted-lock (`ERR_INVALID_SALE_STATE`) — routes/instructions.py:87-93
- §3.6 — insert — ambiguity — quote list `status` filter matches the derived status — quotes.py:84-86
- §3.6 — insert — ambiguity — reinstatement interest line is zero when no `RECORDED` NOD exists (REFERRED case) — calc.py:61-65
- §3.8 scheduling — insert — ambiguity — all six sale outcome fields null at scheduling — notices.py:292-304
- §3.8 registration — insert — ambiguity — registration requires `SCHEDULED`/`CONDUCTED` sale (`ERR_INVALID_SALE_STATE`); `required_deposit_cents` null until qualifying review — routes/auction.py:149-162,213
- §3.8 disqualification — revise — ambiguity — already-bid/wrong-status disqualify → `ERR_INVALID_REGISTRATION_STATE`; empty `reason` → `ERR_INVALID_REQUEST` — auction.py:216-227
- §3.8 conduct — revise — ambiguity — case-state check (`ERR_INVALID_CASE_STATE`) runs second, between sale-state and hold — auction.py:322-327
- §3.8 bids — insert — ambiguity — bid naming nonexistent/wrong-sale registration → `ERR_INVALID_REGISTRATION_STATE`; bid list `placed_at` ties break by creation order — auction.py:268-270; domain.py:135-138
- §3.8 close — insert — ambiguity — "close date" is the logical-clock UTC date at close — workflow.py:225-229
- §3.8 close — insert — ambiguity — debt-payoff disbursement created only when positive; close-created disbursements carry `distribution_run_index` 0 and null `surplus_claim_id` — workflow.py:237-268
- §3.8 void — insert — ambiguity — void `reason` must be non-empty — auction.py:366
- §3.9 deed draft — revise — ambiguity — sale-state check (`ERR_INVALID_SALE_STATE`) runs before the live-deed check — auction.py:392-396
- §3.9 deed record — revise — ambiguity — deed-state check before case-state check; fifteen-day deadline is instant-level (`closed_at` + 15 days exactly) — auction.py:438-445
- §3.9 claim filing — insert — ambiguity — `priority_rank` accepts any integer; claims deadline computed on calendar dates; claim created with `denial_reason` null; claim list `status` filter matches derived status — routes/claims.py:40-57,71,83-84
- §3.9 claim review — revise — ambiguity — `FILED` test reads derived status (expired → `ERR_INVALID_CLAIM_STATE`); no case-state gate at review; APPROVE-amount and DENY-reason violations → `ERR_INVALID_REQUEST` — claims.py:99-117
- §3.9 distribution — revise — ambiguity — nothing-to-do run still permitted when it performs the final close; run on any status other than `SOLD`/`DEED_RECORDED` (incl. `CLOSED`) → `ERR_INVALID_CASE_STATE`; run indices one-based per case, rejected runs consume none — routes/disbursements.py:74-99
- §3.9 PRO_RATA — revise — ambiguity — pool covering the tier total pays each claim its full unpaid amount (no proration) — workflow.py:413-416
- §3.9 residue — insert — ambiguity — "non-terminal" claims = `APPROVED` or `FILED`-and-not-`EXPIRED`; calendar-date window computation — workflow.py:425-438
- §3.9 final pass — insert — ambiguity — derived-`EXPIRED` `FILED` claims do not block the close — workflow.py:459-463
- §3.9 reversal — insert — ambiguity — case-`CLOSED` check runs before disbursement-state check; reversing `TRUSTEE_FEE`/`BENEFICIARY_DEBT_PAYOFF` is accounting-only — disbursements.py:137-157

No changes were needed to the §4 endpoint table (all 56 routes match impl paths/roles) or the §5 error catalogue (all 41 ids and HTTP statuses match `errors.py`).
