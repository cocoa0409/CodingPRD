# Worklog — task_1060_fundraising_gala_auction

Scenario: 1060. Fundraising Gala & Auction Platform (nonprofit): event & ticket/table, sponsor & program-ad, silent/live auction & mobile bidding, paddle-raise & pledge, checkout & payment, donation & receipt, revenue reconciliation, reporting

Difficulty: Expert (scaffold-generator parameter)

## Step 1: Create task directory — pre-assigned

Used pre-assigned directory `tasks/task_1060_fundraising_gala_auction` (Step 1 index scan skipped per launch instruction). Created `workspace/`.

## Step 2: Generate Scaffold — 2026-07-18T17:09:00.000Z

All three files are written and the scaffold lints clean.

**Output** (`tasks/task_1060_fundraising_gala_auction/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 plus `concurrency_rules` and a `global_constants` block; no design keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rule_ids × 2 = **18 instances**.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 9 sections, **35 instances** (30 with full recipes + 5 `excluded_because` stubs).

**Counts (Expert band):** 15 entities · 72 endpoints · 45 errors · 5 roles (segregation_of_duties) · 11 state machines · 8 calculations · 31 ordered validations · 1 OCC concurrency rule.

**Design shape:** Ledger-reconciliation archetype with posture-driven gating (`GalaEvent.posture` OPEN/RESTRICTED/FROZEN derived from event status + existence of a FINALIZED reconciliation run, gating every child mutation). Non-linear machines: parallel dimensions on `AuctionItem` (listing × settlement) and `TicketOrder` (payment × seating); cycles on `ProgramAd` (CHANGES_REQUESTED→SUBMITTED), `CheckoutInvoice` (PARTIALLY_PAID↔PENDING_PAYMENT) and `ReconciliationRun` (PREPARED↔FINALIZED). Dual variants on two different domains: `auction_item_valuation` (PROXY_SETTLED 12500 vs PLACED_AMOUNT 10000) and `pledge_expected_revenue` (BOOKED 300000 vs CASH_BASIS 50000). Combinatorial modes (b) per-unit-then-multiply rounding (33840 vs 33839) and (c) fee tier pinned to the pre-fee subtotal (49900 → fee 1477, total 51377, never re-tiered). Two temporal-overlap geometries: half-open live-lot windows (adjacency allowed) vs closed table-hold intervals with a 15-minute buffer (exactly-15 accepted). Two conserved quantities: money (payment void → `gross_collected_cents` back to 0) and seat inventory (ticket cancel → `seats_reserved` back to 0).

**Verification**
- All three files `yaml.safe_load` cleanly (one `$.data[0].id` capture had to be quoted; fixed).
- Every constant referenced in a formula or rule has a numeric value — declared in each calculation's `constants:` and mirrored in a top-level `global_constants:` block (includes `TABLE_TURNOVER_BUFFER_MINUTES: 15`, `MAX_AD_REVISIONS: 2`, `PLEDGE_LAPSE_GRACE_DAYS: 30`, `DEFAULT_CLOCK_UTC: 2026-07-01T00:00:00Z`).
- All formula-derived assertions were computed with Python (`round_half_up`) before being written as literals.
- No forbidden concurrency vocabulary anywhere (grep-verified); no sibling task directory was read.

Lint verdict, verbatim:
```
Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     30
  Calls scanned (§1.8+§1.9):  398

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Orchestrator verification: all 3 files `yaml.safe_load` OK; no undeclared constants (all-caps residue is enum/state names only).

## Step 3: Copy Shared Files — 2026-07-18T17:09:30.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-18T17:15:00.000Z

PRD generated and verified. Output: `workspace/PRD.md` — 401 lines.

Structure: §1 Introduction (3 paras) · §2 with 9 subsections (RBAC/identity, verbatim §2.2 envelope, pagination, identity+versioning+left-to-right path validation, the 31-step rejection-priority ladder, event posture gate, money/precision, logical clock, OCC + segregation of duties) · §3 with 10 domain subsections (event lifecycle, tables/holds, ticket pricing & dual seating/billing axes, sponsors & ad review cycle, auction floor & the two valuation variants, paddle raise & match waterfall, checkout/payments/settlement cascade, receipts & deductibility, reconciliation & reporting, pledges) · §4 endpoint table · §5 error table.

Hard contract reports (mechanically verified against SCAFFOLD.yaml):
- Field coverage: 89/89 entity fields, 50/50 request bodies, 14/14 query params — PASS
- Rule coverage: 31/31 validations, 1/1 OCC rule, 47/47 transitions across 10 machines, 7/7 calculations, 6 sibling-branch symmetry groups equal density — PASS
- Path purity (§3): 768 backtick tokens scanned, 0 paths / 0 bare methods — PASS

Endpoints: 72 documented in §4 (matches scaffold's 72). Errors: all 45 in §5, each also named in §2/§3 prose.

Constants: every `global_constants` entry and every per-calculation constant appears with concrete numeric value — clock default `2026-07-01T00:00:00Z`; 15-min table turnover buffer (exactly 15 accepted); revision budget 2; pledge grace 30 days; early-bird cutoff 30 days with 15%/10% table/seat rates; 7,500 cents per-seat benefit; match ratio 1.0; fee tiers at 50,000 / 500,000 cents with 2.9%/2.4%/1.9% plus flat 30 cents; FMV de-minimis 1,500 cents; material variance 5,000 cents (inclusive). Both pinned rounding placements stated as pinned.

Neither design YAML was opened.

Orchestrator verification: PRD stable at 401 lines across a 20s durable-stability poll; §4 endpoint rows = 72 == scaffold count.

## Step 5: Generate Unit Tests — 2026-07-18T17:31:00.000Z

Helper files — `test_helpers/` (9 files): `__init__.py`, `types.py` (15 entity TypedDicts + 24 enums), `api_client.py` (73 endpoint methods), `api_errors.py` (46 error IDs + status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (~30 composite helpers across all 5 tiers).

Test files — `test_suite/` (conftest + 7 files): `test_01_event_lifecycle_and_posture.py` (12), `test_02_tables_holds_and_ticket_orders.py` (11), `test_03_auction_floor_bidding.py` (11), `test_04_lot_close_and_valuation.py` (8), `test_05_sponsorships_and_program_ads.py` (6), `test_06_checkout_invoices_and_payments.py` (9), `test_07_appeal_pledges_and_reconciliation.py` (9). **Total: 66 tests**, all collecting cleanly.

Audit: every one of the 18 difficulty instances has >=2 tagged tests; every one of the 30 non-stub corner instances has >=1. All 5 `excluded_because:` stubs left untranslated, all 5 cross-references resolve. 66/66 tests carry exactly one `Design:` line; zero unknown/dual tags. All 113 PRD quotations verified verbatim. No skip/xfail anywhere; pyflakes clean.

Skipped / weakened items (no instance dropped):
1. `Difficulty/transitive_cascade/lot_close_cascades_through_invoice_totals_to_bidder_balance` — terminal assertion `Bidder.outstanding_balance_cents == 12500` NOT emitted. PRD self-contradicts: §3.3 sums `balance_due_cents` over OPEN/PENDING_PAYMENT/PARTIALLY_PAID invoices, §3.5's cascade sentence says recompute "from their PENDING_PAYMENT and PARTIALLY_PAID invoices". At lot close the invoice is still OPEN → a faithful reader could produce 12500 or 0. Tests instead assert the depth-4 chain hammer price → auction line → invoice totals.
2. `Corner/state_machines/retract_bid_on_awarded_lot_is_locked_out` — emitted with `validate_error_is_one_of([ERR_ITEM_NOT_OPEN, ERR_INVALID_STATE])` instead of flat `ERR_ITEM_NOT_OPEN`. §2.5 orders the generic state check (step 8) ahead of the bidding-window check (step 9); with a WON bid on an AWARDED lot both fire and PRD does not commit. Error-precedence silence pattern.

Judgment call flagged: `Corner/state_machines/publish_event_without_any_table_is_rejected` asserts `ERR_INVALID_STATE` for the missing-table precondition — §3.1 states the precondition but names no error ID; `ERR_INVALID_STATE` is the only catalogue candidate and §2.5 buckets unmet transition preconditions there.

## Step 6: Generate Implementation — 2026-07-18T17:24:00.000Z

Implementation written to `workspace/implementation/` — 12 Python modules + launcher:
`start.sh` (guarded dep install, `exec python3 app.py`, binds `0.0.0.0:$PORT`), `requirements.txt`, `app.py` (blueprint registration + error handlers), `core.py` (store, logical clock, envelope, auth, validators, pagination), `calc.py` (posture, rollups, all 7 calculations), `ledger.py` (settlement/unwind cascades), `routes/` (`events.py`, `people.py`, `tickets.py`, `auction.py`, `appeal.py`, `money.py`, `recon.py`).

Self-check: registered route count = 72 (exact match to PRD §4, verified via `url_map.iter_rules()`); `ast.parse` passes on all 12 `.py` files; boot check passed (`PORT=<free> bash start.sh` → `GET /api/events` 200; fresh re-launch returned empty store, confirming no seeding and clean per-test-server reboot; zero tracebacks).

End-to-end smoke verified: early-bird pinned rounding (100001×0.85 → unit 85001 then multiply), proxy-settled vs placed-amount valuation (2100 vs 1000), depth-4 auction-close cascade auto-creating the winner's invoice, tiered fee (rounded before flat 30c), match waterfall capping at `match_cap_cents`, receipt de-minimis + deductibility (benefit 60400 / deductible 41701), partial-pay → void → PENDING_PAYMENT cycle with SoD, posture ladder OPEN→RESTRICTED→FROZEN with carve-outs, 15-minute hold buffer (14 min rejected, exactly 15 accepted), pledge grace/terminality, pagination/RBAC/not-found errors.

Two PRD ambiguities resolved deliberately (flagged for Step 7/9):
1. Bid rejection order — §2.5 numbers `ERR_ITEM_NOT_OPEN`(9) → `ERR_BID_TOO_LOW`(24) → `ERR_NO_PAYMENT_METHOD`(28), but §3.5 prose puts the payment-method gate before the increment floor. Followed §2.5 (the section declaring the strict deterministic ordering).
2. Invoice finalize subtotal gate — a literal pre-sweep `line_subtotal_cents > 0` precondition would make ticket-only checkout impossible. Computes the prospective subtotal (existing lines + sweepable ticket orders + paddle raises) and rejects `ERR_INVALID_STATE` only when that is 0.

Orchestrator verification: 72 `@bp.<method>` route decorators across `routes/*.py` == 72 scaffold/PRD endpoints (no partial-write gap); 66 test functions present.

## Step 7: Run Tests and Iterate — 2026-07-18T17:45:00.000Z

All 8 rounds clean at 66/66. Exiting with the summary.

**Iterations run:** 2 (1 diagnostic sweep with a failure, 1 confirming sweep after the fix).

**Final state:** 66/66 passing across all 8 rounds, 0 failures / 0 errors / 0 skipped.

**Tests deleted:** none. The single failure survived STEP 1 — PRD §1 verbatim covers the rule ("Timestamps are ISO 8601 UTC values rendered with three fractional-second digits.") and §3.8 verbatim states the receipt "stamps `issued_at_utc` from the logical clock", so the outcome is uniquely derivable from PRD prose alone.

**Fixes applied to `test_helpers/`:** none — STEP 2 audit found the fixture, factory, headers, and assertion all faithful to PRD.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/events.py`, `set_clock()` — the logical-clock setter stored the client's raw `to_iso8601` string verbatim (`db.clock = raw`), so a client sending `2026-07-05T00:00:00Z` caused `issued_at_utc` to be emitted without fractional digits. Now normalizes through the existing `fmt_dt(parsed)` renderer before storing, and echoes the normalized value as `current_utc`. Added `fmt_dt` to the module's `core` import list.
- `workspace/implementation/core.py`, `DEFAULT_CLOCK_UTC` — startup clock constant changed from `"2026-07-01T00:00:00Z"` to `"2026-07-01T00:00:00.000Z"` so a receipt issued before any clock advance renders in the same PRD-mandated format.

**Notes worth flagging:**
- The bug was a genuine, if narrow, PRD-compliance gap rather than flakiness: it reproduced deterministically in all 8 rounds of the first sweep. The implementation already had a correct `fmt_dt` renderer used for `created_at`/`updated_at` everywhere else — only the logical clock bypassed it, which is why exactly one test caught it.
- No test asserted on `current_utc`, so normalizing the setter's echo was unobserved by the suite; normalized anyway for consistency with the PRD rendering rule rather than fitting the change narrowly to the one failing assertion.
- The two PRD ambiguities noted in the brief (bid rejection order, invoice finalize subtotal gate) were not implicated in any failure and were left as the implementation had resolved them.

Orchestrator verification: all 8 `results.{1..8}.json` read directly — 66/66, failed 0, errors 0. Sweep ran as 2 waves of 4 via `sweep.sh` (no inline pkill). Step 8 NOT skipped (2 implementation/ fixes).

## Step 8: Finalize PRD — 2026-07-18T17:52:00.000Z

`PRD_FINALIZED.md` written. Step 7's diff contained exactly one behavioral cluster (logical-clock string normalization), so the patch is two sentences across two locations.

**Line counts:** PRD.md 401 lines / 68,433 bytes → PRD_FINALIZED.md 401 lines / 69,044 bytes. Line delta 0.0%; byte delta +0.89%.

**Changes**
- §2.8 The Logical Clock — revise — pinned that the clock stores the *normalized* three-fractional-digit UTC rendering of the supplied `to_iso8601` (regardless of the client's spelling), that this rendered string is what `current_utc` echoes and what any clock-stamped field carries, and that the startup reading therefore renders `2026-07-01T00:00:00.000Z` — `implementation/routes/events.py:26-27`, `implementation/core.py:15,155-157`.
- §4 endpoint table, `POST /api/_clock/set_current_utc` — revise — same normalization/startup-rendering fact restated where an implementer reads the endpoint contract, cross-referenced to §2.8 — `implementation/routes/events.py:20-27`, `implementation/core.py:15`.

**Pre-edit search log**

*Edit 1 (§2.8)* — (a) Subject: the stored representation of the logical clock string and every field derived from or echoing it. (b) Enumerated via `grep -rn "db\.clock|clock_dt()|issued_at_utc|current_utc"` over all impl `.py`: `core.py:105` (init from `DEFAULT_CLOCK_UTC`), `core.py:15` (constant now `...00.000Z`), `core.py:155-157` (`fmt_dt`), `core.py:166-177` (`parse_dt`, accepts `Z`, offsets, space separator, absent seconds, arbitrary fractional digits), `core.py:182` (`clock_dt`), `routes/events.py:26-27` (setter, only writer), `routes/money.py:231` (`issued_at_utc=db.clock`), plus comparison-only consumers `calc.py:117`, `routes/events.py:106,140`, `routes/auction.py:85,176`, `routes/appeal.py:136`. All comparison paths go through `parse_dt`, so normalization is behaviorally invisible to them. (c) Widened the sentence from "a `Z`-suffixed instant" to explicitly cover offsets, missing fractional digits, and more than three digits, since `parse_dt` accepts all of those; wrote "any field stamped from the clock carries" rather than naming `issued_at_utc` alone. Fixed an initially wrong cross-reference (§2.1 → §2.4).

*Edit 2 (§4 endpoint table)* — (a) Subject: the endpoint-row contract for the clock setter — startup default and response body. (b) Enumerated `routes/events.py:20-27` (role gate, `get_dt` validation at `core.py:336-343`, store, echo) and `core.py:15,105`; re-checked the receipt row and §3.8 receipt prose for contradiction. (c) None needed beyond keeping the original instant claim intact and adding the rendering as a separate clause.

Two known PRD ambiguities from the Step 7 notes (bid rejection order, invoice finalize subtotal gate) were NOT patched — outside `<step_7_diff>` scope since no fix, deletion, or test edit traced to them.

## Step 9: Complete PRD — 2026-07-18T17:58:00.000Z

`PRD_COMPLETED.md` written.

**Counts** — source 401 lines / 69,044 chars → completed 401 lines / 72,071 chars (+3,027 chars, no line count change: all edits in-paragraph). 18 changes total: 13 ambiguity-pins, 5 mismatch-revisions.

**Mismatch revisions**
- §3.5 — revise — mismatch — bid rejection order rewritten to the §2.5 sequence (ERR_ITEM_NOT_OPEN → ERR_BID_TOO_LOW → ERR_NO_PAYMENT_METHOD), replacing the "two gates … payment method first" prose — routes/auction.py:177-190
- §3.7 — revise — mismatch — finalize gate is the *prospective* subtotal (existing non-fee lines + sweepable UNBILLED orders + UNSETTLED gifts), ERR_INVALID_STATE only when that is 0 — routes/money.py:77-82
- §3.5 — revise — mismatch — winner's balance recomputes over OPEN + PENDING_PAYMENT + PARTIALLY_PAID invoices (PRD had omitted OPEN, contradicting §3.3) — calc.py:57-65
- §3.2 — revise — mismatch — dropped "published-or-draft"; table creation has no event-`status` precondition and is not posture-restricted — routes/events.py:168-177
- §3.9 — revise — mismatch — run finalize/reopen do not write the event row; event `version`/`updated_at` unchanged — routes/recon.py:85-87, 100-103

**Ambiguity pins**
- §2.3 — insert — non-integer limit/offset and out-of-enum list filters are ERR_INVALID_REQUEST; undeclared query params ignored — core.py:346-375
- §3.3 — insert — order creation consumes every matching still-HELD hold on that table, regardless of time window — routes/tickets.py:47-51
- §3.3 — insert — cancelling a PAID order leaves invoice_id, invoice lines/totals, guest balance and event rollups untouched — routes/tickets.py:103-117
- §3.4 — insert — sponsor confirm `paid_amount_cents` must be at least 0 — routes/people.py:190
- §3.4 — insert — sponsor withdraw checks PENDING first; a PLACED ad also yields ERR_INVALID_STATE — routes/people.py:208-212
- §3.4 — insert — REQUEST_CHANGES missing `notes` is a §2.5 step-3 shape check (ERR_INVALID_REQUEST), evaluated before the ad id resolves — routes/people.py:270-273
- §3.4 — insert — ad placement `page_number` must be at least 1 — routes/people.py:325
- §3.5 — insert — valuation `variant` is mandatory and must be one of the two spellings, else ERR_INVALID_REQUEST — routes/auction.py:146-152
- §3.5 — insert — at lot close the earliest-created OPEN invoice is used; an auto-created one gets `cover_processing_fee` false — ledger.py:6-16
- §3.7 — insert — sweep order (created_at asc, all TICKET lines before all PADDLE_RAISE, appended after existing lines); PROCESSING_FEE always rewritten last — routes/money.py:84-93, calc.py:183-196
- §3.7 — insert — payment void `reason` is required non-empty, else ERR_INVALID_REQUEST — routes/money.py:183
- §3.7 — insert — voiding an OPEN invoice does not recompute the guest balance or event rollups — routes/money.py:113-116
- §3.10 — insert — pledge installment `amount_cents` must be at least 1 — routes/appeal.py:113

Notable finding: both generator-flagged items were real, and the §3.5 outstanding-balance sentence was a third mismatch — the PRD contradicted *itself* (§3.3 listed OPEN, §3.5 omitted it), with the implementation siding with §3.3. This is the same self-contradiction Step 5 cited when it dropped the `transitive_cascade` terminal assertion.

---

## PIPELINE COMPLETE — all 9 steps. Final: 66/66 × 8 rounds, 0 failures / 0 errors.
