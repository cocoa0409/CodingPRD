
## Step 7: Run tests and iterate — 2026-08-08T19:15:00.000Z

All checks pass. Here is the final report.

## Result: clean 8-round sweep, 86/86 in every round

**Iterations run: 2** (two full 8-round sweeps = 16 rounds total).

### Iteration 1 — 2 deterministic failures (all 8 rounds, identical)

Both were **test bugs (STEP 2)**; the implementation was correct in both cases and was **not touched**.

### Tests deleted
**None.** Both failures were repairable into strictly-more-PRD-faithful tests, so no coverage was lost.

### Fixes applied to `test_suite/`
1. `test_suite/test_05_papers_trailers_and_the_gate.py` — `test_removing_the_last_line_returns_the_manifest_to_planned`: the fixture chain called `load_and_dispatch(...)`, leaving the manifest **DISPATCHED**, then asserted the revert to `PLANNED`. The cited PRD sentence names the transition as `LOADING -> PLANNED`; §3.9 declares **no** `DISPATCHED -> PLANNED` transition anywhere (and says nothing about unwinding the `HAUL` charge line that dispatch appends), so "stays `DISPATCHED`" is a defensible faithful reading and the test as written failed unique derivability. Replaced `load_and_dispatch` with `open_manifest` + `add_lot_to_manifest`, so the manifest sits in `LOADING` — the exact source state the PRD names — and added two assertions pinning `status == "LOADING"` and `haul_charge == 250.00` before the removal. All original assertions retained.
2. `test_suite/test_08_money_after_the_hammer.py` — `test_a_released_settlement_refuses_a_second_release_but_admits_an_adjustment`: posted `adjustment_amount: -100.00`, which **PRD §2.9 rung 6 forbids verbatim** ("payment and adjustment amounts strictly greater than 0" -> `ERR_INVALID_REQUEST`). Changed to `+100.00` and re-derived the expectations from PRD §3.10's net formula (`... plus adjustment_total`): `adjustment_total 100.00`, `net_amount 11944.41 + 100 = 12044.41`. Added the two governing PRD quotes to the docstring.

### Fixes applied to `test_helpers/` — none. Fixes applied to `implementation/` — none.

### Clean-sweep verification numbers
- 8/8 `results.N.json` present and parseable; each `passed=86 failed=0 total=86`, **86 individual test rows**, status set exactly `{passed}`.
- Sorted test-name lists **byte-identical across all 8 rounds** (86 names).
- `def test_` count = **86** = runner's `collected 86 items` = `Design:` tag count = **86**.
- `skip` / `xfail` / `skipif` occurrences: **0**.
- `grep -rE "sqlite|json\.dump|pickle|/tmp|datetime\.now|utcnow|time\.time\(\)"` over `implementation/`: **empty**.
- Exactly **1 `Killed` per round log** (rounds 1-8), each immediately after test #1's name; **0 tracebacks** in all 8 logs.
- `find implementation test_suite test_helpers -newer results.1.json`: **empty** — nothing edited after the sweep.

### The twelve friction verdicts

| # | Friction | Verdict |
|---|---|---|
| 1 | Yardage day count across a consignment's lots | **AGREEMENT-BY-CONSTRUCTION** |
| 2 | Zero-amount seller charge lines | **CLEAN** |
| 3 | Offset when one party has two settlements | **CLEAN** |
| 4 | What a DOA memo adds to `credit_memo_total` | **AGREEMENT-BY-CONSTRUCTION** |
| 5 | Rung 43's credit-memo cap | **CLEAN** |
| 6 | Rung 20's re-weigh cap denominator | **CLEAN** |
| 7 | Gate G5's reach vs rung 15's scope | **AGREEMENT-BY-CONSTRUCTION** |
| 8 | Purchase-void hop 3 -> settlement `ADJUSTED` | **CLEAN** |
| 9 | `loss_type` spelling | **CLEAN** (PRD §2.9 names `DEAD`/`CONDEMNED`/`WITHDRAWN` verbatim — not un-adjudicated for a PRD-only reader) |
| 10 | Bid-restoration triggers | **CLEAN** |
| 11 | Governing ticket under pencil shrink | **AGREEMENT-BY-CONSTRUCTION** |
| 12 | `max_draft_lb` / `head_on_draft` | **AGREEMENT-BY-CONSTRUCTION** |

**No DEPENDS verdicts** — no test needed deleting for unfairness.

Re-derived numbers for the five AGREEMENT-BY-CONSTRUCTION verdicts:

- **F1.** The only multi-lot `PER_HEAD_DAY` consignments are test_06's 15-head (lots 10+5) and test_07's `_feed_settlement` 10-head (lots 7+3), and in both **no lot is released before the close**, so every candidate end instant is the close clock. test_06: `checked_in_at` 2026-06-01T08:00Z -> close 2026-06-02T10:00Z = 93 600 s; 93 600/86 400 = 1.083 -> ceil 2 days. Consignment-level: 1.75 x 15 x 2 = **52.50**. Per-lot: 1.75x10x2 + 1.75x5x2 = 35.00 + 17.50 = **52.50**. test_07 feed: 08:00Z -> 20:00Z = 43 200 s -> ceil 1 day. Consignment-level 1.75 x 10 x 1 = **17.50**; per-lot 1.75x7x1 + 1.75x3x1 = 12.25 + 5.25 = **17.50**. Identical both times.
- **F4.** `extended_amount` = 182.50 x 6790/100 = **12 391.75**; per head = 12 391.75/10 = 1239.175 -> half-up **1239.18**; x `doa_head` 2 = **2478.36**. Supplied `amount` = **2478.36**. Both readings => `credit_memo_total` 2478.36, `total_due` 12 391.75 + 30.98 - 2478.36 = 9944.37. Coincide exactly.
- **F7.** The only endpoints exercised against a `RELEASED` settlement are `settlements/{id}/release` (refused under **both** the broad-G5 and narrow-rung-15 readings) and `settlements/{id}/adjust` (the named exemption under **both**). The readings differ only outside that pair, which no test enters.
- **F11.** No pencil-shrink lot in the suite ever holds two `CAPTURED` tickets: consignment A of `_two_bases_scenario` has exactly one; `_expiring_scale_scenario` has one CAPTURED plus one that never captures. With a single candidate, every governing rule selects the same ticket — 7200 - 200 = 7000; 7000 x 0.97 = **6790**.
- **F12.** Every draft's `head_on_draft` equals its lot's `head_count` (factory default 10 on all 10-head lots; explicit 8, 5, 40 where head counts differ), and the heaviest `gross_weight_lb` in the suite is **26 200** against `max_draft_lb` **60 000**. A policing implementation and a recording-only one are observationally identical.

### Near-miss register (fair only by accident)

| Test / fixture | Friction | The one value or missing call that keeps it fair |
|---|---|---|
| `_two_consignments_on_different_commission_bases`, `_floor_and_cap_settlements` (test_07) | 3 | Buyer is `create_buyer_party()` (Midwest Packing), **not** `scn.consignor`. Same consignor already owns two settlements; make the buyer the consignor (as the buy-back test does) and both settlements pour against one invoice -> adjudication-dependent. |
| `_closed_day_with_one_sold_and_one_unfinished_lot` (test_06), `_feed_settlement` (test_07) | 1 | **No `release_lot` call** before the close. Release the earliest-created lot a day early and consignment-level vs per-lot day counts diverge. |
| `test_dead_on_arrival_credit_memo_cascades_...` (test_08) | 4, 5 | Supplied `amount` is exactly **2478.36**, the computed credit. Any other amount separates "supplied amount" from "computed amount"; and any amount near `total_due` 12 422.73 separates the rung-43 cap readings. |
| `test_charge_lines_are_append_only_rows_with_no_version` (test_06) | 2 | It lists every sale-day line but asserts **no count** and never requires/forbids `FEED` (ration `NONE` -> 0.00). One `len(lines) == N` and it becomes adjudication-dependent. |
| `_two_bases_scenario` lot_b (test_02) | 6, 11 | Stops at **2 tickets** (1 SUPERSEDED + 1 CAPTURED). Two more re-weighs and the "all tickets vs captured-only" denominator bites; a second captured draft on the *pencil-shrink* lot_a would expose the governing-ticket rule. |
| `_hammered_lot_with_the_pre_sale_reading` (test_10) | 8, 10 | **One** registration (so no `OUTBID` bid to restore) and **no `close_day_and_settle`** (so no settlement exists at void time). One extra bidder, or one close before the void, and both frictions become observable. |
| `test_a_released_settlement_refuses_a_second_release...` (test_08) | 7 | Touches only `release` + `adjust`. Any third settlement-mutating call after release exposes G5's reach. |

### Additional spot-audit
- **106 distinct asserted response-field names**, all appearing verbatim in `PRD.md` (the only 6 non-matches are local scenario-dict keys for header bundles: `*_headers`).
- **Every numeric literal hand-derived** from PRD-stated formulas — settle weight/shrink, `PER_CWT`/`PER_HEAD` extensions, tiered vs flat commission with floor (4.00/head) and cap (450.00), per-head-day vs flat yardage, per-line feed rounding (29.51 + 12.65 = 42.16 != 42.15), checkoff/brand/indemnity with 0.50-25.00 bounds, bond-processing (0.0025, cap 150) vs cash-handling (0.75/head, floor 5.00) buyer fees, per-mile haul (4.85/mi floored at 250.00) vs per-head-flat (12.00/head) with BY_HEAD proration 120.00 + 96.00 = 216.00, the offset pour 11 944.41, bond multipliers 1.5/1.0/0.0, and the settlement balance identity. All reconcile.
- **Every instant assertion is semantic** (`assert_same_instant` / `assert_same_date`); zero raw string comparisons on `*_at` fields.
- **Every asserted list index** traces to PRD §2.3's verbatim ascending-`created_at` ordering rule; all `rows[0]`/`rows[-1]` helper picks operate on filters that return a single row.
- `money_reconciliation_ok is True` is asserted only in `test_06`, which **never opens a manifest** — the impl-flagged post-dispatch `HAUL` discrepancy is never exercised, so no test contradicts that faithful reading.

**Orchestrator independent verification (Step 7):** all 8 `results.N.json` re-parsed independently -> 86 rows each, `passed=86 failed=0 total=86`, status set exactly `{'passed'}`, sorted name-list MD5 byte-identical across all 8 rounds; `def test_` 86 == `Design:` tags 86; 0 skip/xfail/skipif; impl grep for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` empty; independent route diff (scaffold `endpoints[]` vs booted in-process `app.url_map`, params normalized) -> **78/78, 0 missing, 1 extra = Flask's built-in `/static/<path>`**; exactly one `Killed` and 0 `Traceback` per round log; `find ... -newer results.1.json` returns only sibling results files and `SWEEP_DONE`, no source file.
