# Worklog — task_0937_livestock_auction_sale_barn

Scenario (verbatim): `937. Livestock Auction & Sale Barn: consignment & lot/pen, weigh-in & drovers, buyer registration & credit, ring/sale & price-per-cwt, commission & yardage/feed, brand/health inspection & CVI, check-out & settlement, trucking`

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-08T17:16:00.000Z

Created `tasks/task_0937_livestock_auction_sale_barn/` and `tasks/task_0937_livestock_auction_sale_barn/workspace/`. Index 0937 = highest existing (0936) + 1.

## Step 3: Copy shared files — 2026-08-08T17:16:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0937_livestock_auction_sale_barn/workspace/INSTRUCTION.md` (1424 bytes). Run early since it has no dependency on Step 2.

## Step 2: Generate scaffold — 2026-08-08T18:08:00.000Z

All three scaffold artifacts are written and clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_0937_livestock_auction_sale_barn/`
- `SCAFFOLD.yaml` (§1.0–§1.7 + `global_constants`, `gate_precedence`, `conservation_invariants`, `charge_line_classification`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Density

| Dimension | Target | Delivered |
|---|---|---|
| Entities | 16–18 | **18** |
| Endpoints | 65–78 | **78** |
| Error codes | 34–40 | **41** (1 over; every one reachable and distinct) |
| Calculations | 20+, 6+ dual-variant | **26, 7 dual-variant** |
| State-machine axes | 12+, ≥8 non-linear | **16, 15 non-linear** |
| Validation ladder | 34+ rungs | **43 rungs, single total order** |
| OCC rules | 3 | **3** (Lot / BuyerRegistration / LoadManifest) |
| Conservation invariants | 4 | **6** |
| Deepest cascade | 5 | **5** (SaleDay→Lot→Consignment→Settlement→ChargeLine) |
| §1.8 instances | ≥18 | 18 (9 rules × 2) |
| §1.9 instances | breadth | 52 (50 recipes + 2 `excluded_because` stubs) |

7 dual-variant calcs: `settle_weight`, `lot_extension`, `seller_commission`, `yardage_charge`, `buyer_side_fee`, `haul_charge`, `haul_proration`. Second cascade (depth 4) from a different trigger: `purchases/{id}/void`. Third (depth 3): `pen-moves/{id}/status → COMPLETED`.

## Constants

**56 declared constants**, all with numeric/string values. Residual ALL_CAPS tokens after subtracting declared constants, error ids and enum members: `BRAND_FEE`, `BUYER_FEE`, `INDEMNITY_FEE` — all three are `ChargeLine.charge_type` **enum members**, not constants. No undeclared constant remains.

## Reachability-audit self-repairs (4)

1. **Rung 19 made its own side-effect unreachable.** `ERR_WEIGH_TICKET_OPEN` originally applied to `POST /pen-moves`, which would have blocked ever creating a move while a draft was open — killing the "pen move mid-weigh-in voids the open ticket" side-effect. Narrowed the rung to `POST /weigh-tickets` only.
2. **`Consignment SORTED → CHECKED_IN` was unreachable.** Withdrawing a *lot* originally moved head into `head_withdrawn`, so `head_unassigned` never rose above 0. Redefined: withdrawing a lot returns its head to `head_unassigned` (still on the yard); `head_withdrawn` counts only lot-less withdrawals. Invariant `INV_CONSIGNMENT_HEAD` still balances.
3. **`Purchase.ADJUSTED` was unobservable.** The `ADJUSTED → INVOICED` edge fired inside the same request that produced ADJUSTED. Re-triggered it on a subsequent `payments` call, making ADJUSTED durable.
4. **`ChargeLine.side` / `revenue_class` enum members were dead, and `DOA_CREDIT` was double-counted.** Added an explicit `charge_line_classification` table producing all three `revenue_class` values (incl. `PASS_THROUGH` for BRAND_FEE and HAUL), and excluded `DOA_CREDIT` lines from the money-balance sum since `credit_memo_total` already carries them.

Two dropped enum values for the same reason: `Bid.PLACED` (transient, never observable → initial state is `WINNING`) and `Purchase.PENDING`.

**Arithmetic feasibility** was computed, not eyeballed: the commission per-head floor (40.00 on a 500.00 gross over 10 head), the 450.00 cap (720.00 tiered on a 24000.00 gross), the indemnity floor/cap boundaries (gross < 333.34 / > 16666.67), the `MIN_HAUL_CHARGE` boundary (miles < 51.55), and the feed rounding divergence (42.16 per-line vs 42.15 sum-first) are each reachable with declared head/weight/price ranges. Every formula-derived assert literal was produced by running the formula in Python.

## Verification

- `yaml.safe_load` passes on all three files.
- `scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    78
  §1.1 entities declared:     18
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1157

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

- Placeholder closure: 0 unbound `${var}` across 1157 calls and all asserts.
- Instance names: 70 total, 0 duplicates across both design files.
- Dangling `grounds` refs: 0.
- Error coverage: all 41 codes are named by at least one design instance.
- Forbidden concurrency vocabulary: absent.
- Every entity has a create path (14 direct, 4 cascade-created with reverse-reachability GETs); every declared status is written by an endpoint or a declared cascade.

No sibling task directory was read.

**Orchestrator independent verification (Step 2):** all three files re-parsed with `yaml.safe_load` (3815 / 2012 / 3648 lines); independent ALL_CAPS sweep filtered to constant-shaped tokens (`*_LIMIT|*_WINDOW|*_DAYS|*_RATE|*_FEE|*_CAP|*_PCT|MIN_*|MAX_*|DEFAULT_*|*_INCREMENT|*_TOLERANCE`) returns exactly `BRAND_FEE`, `BUYER_FEE`, `INDEMNITY_FEE` — all `charge_type` enum members (`BRAND_FEE_PER_HEAD` is separately declared). 56 declared constants confirmed. Entities 18 / endpoints 78 / state_machines 16 confirmed from the parsed YAML.

## Step 4: Generate PRD — 2026-08-08T18:22:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0937_livestock_auction_sale_barn/workspace/PRD.md`.

## Size
**491 lines, 14,695 words.** Structure: §1 Introduction (3 paras) → §2 with 11 subsections → §3 with 11 subsections → §4 endpoint table → §5 error table. Written in 4 bounded appends, no oversized single write.

## Completeness gate (all verified programmatically against SCAFFOLD.yaml)

1. **Endpoints: 78/78.** Every scaffold `endpoints[]` entry appears as a `| Method | `path` |` row in §4 (exact method+path tuple match, 0 missing).
2. **Error codes: 41/41** appear verbatim in the document.
3. **Ladder rungs: 43/43**, rendered as a single stated total order in §2.7 (rows 1…43 contiguous), with the explicit instruction that evaluation stops at the first failing rung and rungs 11–15 are the five gates in gate-precedence order.
4. **Constants: 54/56 numeric-or-string values appear literally.** The two exceptions are `MONEY_ROUNDING` and `WEIGHT_ROUNDING`, whose value `round_half_up` is rendered as the phrase "rounded half up" throughout (the skill forbids copying the symbolic token). Every numeric constant — including the ones with no independent narrative hook (`CHECKOFF_PER_HEAD` 1.00, `YARDAGE_MIN_DAYS` 1, `MAX_RETEST_COUNT` 1, `UNSECURED_LIMIT_MULTIPLIER` 1.0, `CASH_ONLY_LIMIT_MULTIPLIER` 0.0) — is stated with its value in business context.
5. **State machines: 16/16 axes, 97/97 transitions** described, including both parallel `Lot` axes on one row, all five non-linear re-entry/revert/loop edges (`BIDDING_CLOSED → RINGING`, `SORTED → CHECKED_IN`, `NO_SALE → READY`, `SOLD → NO_SALE`, `LOADED → BUYER_PEN`, `OUTBID → WINNING`, `ADJUSTED → INVOICED`, `RELEASED → ADJUSTED → RELEASED`, `LOADING → PLANNED`, `FAILED → PENDING`).
6. **Depth-5 cascade: all 5 hops hop-by-hop in §3.10**, plus the interposed invoicing step between hops 3 and 4. There is **no §2-level summary of the cascade** — deliberately, to eliminate summary/detail drift. The only other mentions are §1's phrase "five-hop settlement cascade" and §4's description column (verbatim from the scaffold), neither of which enumerates hops. The 4-hop purchase-void cascade is likewise stated once, hop-by-hop, in §3.11.

## Hard Contracts

```
Field coverage check:
- entities[].fields: 163 required, 163 present, 0 missing
- endpoints[].request_body/input: 91 required, 91 present, 0 missing
- endpoints[].query_params: all present (folded into the 176-token dedup set)
Total required set: 176 unique tokens; 176 present; 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 43 checked, 43 expressed as one total order, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 97 checked, 97 fully expressed, 0 missing
- calculations[]: 26 checked, 26 fully expressed in precise prose (7 dual-variant rendered with both branches at equal density), 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 78 checked, all expressed, 0 missing
- entities[].fields[] structured content: 163 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 dual-variant calcs + 5 gate scopes + 2 loss paths checked, 0 asymmetric
- conservation invariants: 6 checked, 6 expressed as computed-boolean formulas, 0 missing
- charge_line_classification: 10 charge types × side × revenue_class, all expressed
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 787
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Un-adjudicated friction points

These are rendered **neutrally** in the PRD (facts stated, outcome not asserted) unless noted:

1. **Yardage day count when a consignment's lots disagree.** `days_on_yard` is scaffold-defined over *one lot's* occupancy window, but `yardage_charge` multiplies the rate by *consignment-level* billable head and a single day count. Divergence is reachable: a BONDED buyer's lot can be released before close (ending at `released_at`) while sibling lots end at the close instant. **Reading A:** one count per consignment, derived from a single representative end instant (e.g. the close instant for the whole consignment). **Reading B:** per-lot day counts, with the charge summed per lot rather than levied on aggregate billable head. PRD says explicitly it does not pin this.
2. **Zero-amount seller charge lines.** Hop 5 says the seven seller charge types "are appended". **Reading A:** all seven lines are always written, including a 0.00 `FEED` line when `ration_type` is `NONE`. **Reading B:** only lines with a non-zero computed amount are written. PRD states the parenthetical that this is unstated.
3. **Settlement offset when one party has two settlements.** The pour "does NOT itself change any invoice balance in this pass". **Reading A:** each settlement of the same consignor party pours against the *same* untouched `balance_due` values, so the same balance can be offset twice. **Reading B:** within the close pass, a later settlement sees balances already reduced by an earlier settlement's pour. PRD states it does not pin this.
4. **What a DOA credit memo adds to `credit_memo_total`.** The endpoint takes both `amount` and (`purchase_id`, `doa_head`), and `doa_credit_amount` is computed independently. **Reading A:** `credit_memo_total` rises by the supplied `amount`. **Reading B:** it rises by the computed `doa_credit_amount` (or by its delta versus the prior cumulative credit). PRD states it does not pin this.
5. **Rung 43's credit-memo cap.** Scaffold reads "credit memo amount is `<= BuyerInvoice.total_due` minus prior memos", but `total_due` *already* subtracts `credit_memo_total`. **Reading A (transcribed literally in the PRD):** the cap is `total_due − credit_memo_total`, i.e. memos are subtracted twice. **Reading B:** the cap is simply the current `total_due`, the "minus prior memos" clause being a restatement of how `total_due` is formed.
6. **Rung 20's re-weigh cap denominator.** "The lot's ticket count minus one." **Reading A:** all tickets on the lot count, including `VOIDED` and `SUPERSEDED` ones. **Reading B:** only tickets that are or were `CAPTURED` count, so voiding a bad draft restores headroom.
7. **Gate G5's reach vs. rung 15's enumerated scope.** G5's stated scope is "no further mutation of a `RELEASED` settlement except adjust"; rung 15's `applies_to` names only `POST /sale-barn/settlements/{id}/release`. **Reading A:** the broad scope — any settlement-touching write other than adjust answers `ERR_SETTLEMENT_RELEASED`. **Reading B:** the narrow scope — only the release endpoint. PRD states both facts side by side and explicitly declines to collapse them.
8. **Purchase-void hop 3 driving a settlement to `ADJUSTED`.** The declared `Settlement` axis contains only `RELEASED → ADJUSTED` (via the adjust endpoint). **Reading A:** hop 3 drives *any* existing settlement (`DRAFT`, `HELD`, `RELEASED`) to `ADJUSTED` as a system edge outside the declared axis. **Reading B:** only a `RELEASED` settlement is driven to `ADJUSTED`; a `DRAFT`/`HELD` one merely recomputes `gross_amount` and keeps its status.
9. **`loss_type` vocabulary spelling.** The scaffold names only `WITHDRAWN` explicitly; the other two members are implied by the counters `head_dead` and `head_condemned`. The PRD asserts `DEAD`, `CONDEMNED`, `WITHDRAWN` (an implementable set is required), but the exact spelling of the first two is not scaffold-pinned.
10. **Bid restoration triggers.** The `OUTBID → WINNING` edge names only two triggers (the holding registration revoked, or the purchase voided). **Reading A:** restoration is limited to those two. **Reading B:** restoration fires whenever a lot's `WINNING` bid is voided, which would also cover the no-sale transition and close-cascade hop 2. PRD states only the two named triggers.
11. **Governing ticket under pencil shrink.** The `settle_weight` formula says the governing ticket is the `CAPTURED` ticket with the highest `ticket_seq` (basis-independent); the pencil-shrink variant gloss says the shrink applies to "the *first* captured net weight". PRD applies the formula uniformly (highest-seq `CAPTURED` governs on both bases) and notes only that no stand time is enforced under pencil shrink.
12. **`max_draft_lb` and `head_on_draft` are recorded but unpoliced.** No ladder rung compares a ticket's `gross_weight_lb` to the scale's `max_draft_lb`, nor `head_on_draft` to the lot's `head_count`. PRD describes both fields without asserting any enforcement.

## Step 5: Generate unit tests — 2026-08-08T18:55:00.000Z

## Summary

Generated `test_helpers/` (9 modules) and `test_suite/` (conftest + 10 test files) for `task_0937_livestock_auction_sale_barn`. **86 tests**: **37 queue A** (Difficulty) + **49 queue B** (Corner).

### Exit-check numbers
- `def test_` count = **86**; `Design:` tags = **86**; **0 untagged, 0 dual-tagged**, every tag resolves to a real non-stub instance name (namespace + section/rule_id verified against both yamls). No duplicated *(file, test)* pairs; repeats are only the intended >=2-per-difficulty-instance.
- Coverage: **all 18 difficulty instances have >=2 tests** (the five-hop cascade has 3); **49 of 50 non-stub corner instances have >=1 test** (1 skipped, below). Both `excluded_because` stubs (`corner_indemnity_fee_floor_and_cap_constants_applied`, `corner_lot_extension_per_head_basis_ignores_settle_weight`) were **not** translated; their cited difficulty instance `commission_floor_and_cap_nesting_mode_a` resolves and owns those assertions.
- **0** occurrences of `pytest.mark.skip` / `xfail` / `skipif` anywhere.
- **203 PRD citations** machine-checked: every quoted sentence survives a whitespace-normalised literal match against `workspace/PRD.md` (0 misses).
- **100 distinct response/request field names** asserted in `test_suite/` — all appear verbatim in PRD.md (same check over `test_helpers/`: 100 names, only the local `TEST_USERS` dict keys are non-PRD).
- Every timestamp equality routes through `assert_same_instant` (3 sites: `checked_in_at`, `scheduled_end_at` x3, `last_move_completed_at` vs `completed_at`); all other `*_at` uses are null/not-null. Calendar-date fields (`valid_through`) go through a new `assert_same_date` so a full-ISO rendering can't fail a date claim.
- List-ordering assertions: only the pagination test, traced to §2.3 "Results are always sorted by `created_at` in ascending order".
- Role headers: every party-backed call uses `make_consignor_headers/make_carrier_headers(<real Party id>)`; consignor, buyer and carrier are distinct parties everywhere except the buy-back instance, where they are intentionally the same party.
- `pytest --collect-only`: **86 collected**, imports clean, no unused imports.

### Numeric derivation (all re-derived in Python with `Decimal`/ROUND_HALF_UP, not copied)
Hand-derived chains: settle weight (7000x0.97 = 6790, avg 679.0, MEDIUM); extensions (182.50x6790/100 = 12391.75; 183.50 -> 12459.65; 150.00 -> 10185.00; PER_HEAD 500.00 / 24000.00 / 9125.00); commission tiered 371.75, flat 180.00, floor branch max(25.00, 40.00) = 40.00, cap branch min(720.00, 450.00) = 450.00; yardage 35.00 / 52.50 / 17.50 / 70.00 / flat 75.00; feed 29.51 + 12.65 = 42.16 (!= 42.15); statutory 10.00; brand 12.00; indemnity 18.59 / 0.75 / 25.00 / 0.00; buyer fee 30.98 (bond) and 7.50 (cash); invoice totals 12422.73 / 12399.25 / 9944.37 / 8944.37; nets 11944.41, 12136.16, 11926.91, 419.75, 23367.00, -59.66, 11904.41, 0.00, 11844.41, -17.50; offset 11944.41; effective limits 75000 / 1000 / 20000 / 15000 and exposures 12391.75 / 24783.50 / 12459.65 / -12422.73; haul max(4.85x40, 250) = 250.00 and 12x18 = 216.00 with BY_HEAD shares 120.00 / 96.00; DOA 1239.18x2 = 2478.36; validity dates 06-02 / 06-11 / 07-31 / 05-01; day counts 26h->2, 12h->1, exactly 86400s->1; crew blocked-until 09:45 and 10:15.

### Friction handling
**AVOIDED** (10 of 12): #7, #8, #9, #10, #12 never touched; #1 avoided by construction (every settlement's lots end their day count at the same close instant, so per-lot and consignment-level counts coincide); #3 avoided (never two settlements for one consignor party).

**AGREEMENT-BY-CONSTRUCTION (derived both readings numerically):**
1. **#4 + #5 — DOA credit memo** (`corner_doa_credit_memo_...`). Reading A: `credit_memo_total` rises by the supplied `amount` = 2478.36. Reading B: it rises by the computed credit = round(12391.75/10) = 1239.18, x2 = **2478.36**. Identical => `total_due` = 12391.75 + 30.98 - 2478.36 = **9944.37** under both. Rung-43 cap: reading A = `total_due - credit_memo_total` = 12422.73 - 0.00 = 12422.73; reading B = `total_due` = 12422.73 — identical (no prior memos), and 2478.36 <= 12422.73, so the memo is accepted either way.
2. **#2 — zero-amount charge lines.** No test asserts a charge-line count; only lines that are non-zero under both readings are asserted (YARDAGE 17.50/52.50, COMMISSION 371.75, CHECKOFF_STATE/NATIONAL 5.00, BRAND_FEE 12.00, INDEMNITY_FEE 18.59, BUYER_FEE, DOA_CREDIT). `money_reconciliation_ok` is unaffected because a 0.00 FEED line contributes 0 to the charge-line term under both readings (12422.73 = 11926.91 + 495.82 either way).
3. **#11 — governing ticket under pencil shrink.** Every pencil-shrink lot asserted on has exactly **one** CAPTURED ticket, so "highest-seq CAPTURED" and "first captured" are the same row (6790). The two-ticket lot is STAND_ACTUAL, where the PRD's own words settle it (6900).
4. **Roll-up timing** (not on the friction list, but a genuine two-reader gap): `SaleDay.total_gross_sale_value` is only defined in §3.10's close-cascade roll-up list, so a pre-close reading is not uniquely derivable. The compensating-invariant test therefore reads the value **before** the hammer and asserts the post-void value equals it (0.00 = 0.00 under "derived on read"; 0.00 = 0.00 under "recomputed at close"), and never asserts the 12391.75 mid-state.

**SKIPPED — 1 instance:** `Corner/validations/corner_fourth_weigh_ticket_exceeds_reweigh_cap` — **friction #6**. Under "all tickets count", the fourth open is refused; under "only CAPTURED tickets count", only one ticket is ever CAPTURED (each capture supersedes the prior), so the re-weigh count is 0 and the fourth open is *accepted*. No fixture makes the two readings agree on a rejection.

**Error-precedence relaxation (Silence pattern):** `corner_release_without_any_load_assignment_is_rejected` uses `validate_error_is_one_of([ERR_LOAD_NOT_ASSIGNED, ERR_INVALID_STATE])` — the lot sits at `BUYER_PEN`, and rung 16's from-set check on `LOADED -> RELEASED` sits above rung 41; the PRD does not collapse the two. All other assertions of that instance (custody unchanged, `released_at` null, pen occupancy 10) are kept.

**Two assertions dropped for PRD silence (instance otherwise emitted):** `avg_weight_lb is null` before capture (PRD pins `settle_weight_lb` null and `weight_class` NONE but never says avg is null), and the `SaleDay.total_gross_sale_value` line of the consistency instance (roll-up timing, above).

### Isolation
I did **not** read, ls, glob or grep `workspace/implementation/`. It appeared on disk during the run (visible only as a directory name when listing `workspace/`); its contents were never opened. No sibling `task_*` directory was read.

Key paths: `test_helpers/fixtures.py` (5-tier composite setup: primitives -> checked-in consignment -> ready/sold lot and the ring -> papers/trailers/gate -> close-and-settle), and `test_suite/`.

## Step 6: Generate implementation — 2026-08-08T18:56:00.000Z

Implementation complete and verified.

## Deliverable
`workspace/implementation/` — **37 Python modules, 4,465 lines**, plus `start.sh` and `requirements.txt`. Flask + in-memory dicts only; no seeding, no disk persistence, no wall-clock reads (logical clock starts at `2026-05-01T00:00:00Z` every boot).

**Isolation honored:** I did not read, ls, glob, or grep `test_suite/` or `test_helpers/` (they appeared on disk during my run — I ignored them completely), nor `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml`, nor any sibling `task_*` directory.

## Completeness gate (programmatic, not eyeballed)
Scaffold `endpoints[]` normalized vs. booted `app.url_map`: **MATCHED 78 / MISSING [] / EXTRA []**.

## Three standing bug classes

**1. Timestamp rendering — one policy, one producer (`clock.render_instant`).** Server-minted instants (`created_at`, `updated_at`, `checked_in_at`, `penned_at`, `released_at`, `opened_at`, `captured_at`, `completed_at`, `last_move_completed_at`, `dispatched_at`, `api_request_timestamp`) always render `YYYY-MM-DDTHH:MM:SS.mmmZ` per PRD §2.4. Caller-supplied instants are echoed **verbatim** (`scheduled_start_at`, the clock endpoint's `current_utc`). The one derived-from-caller instant, `scheduled_end_at`, renders in its source string's own style via `render_derived`. HTTP-verified: `created_at == "2026-05-01T00:00:00.000Z"`; clock echo of `"2026-05-02T06:30:00.250Z"` verbatim; start `"...09:00:00Z"` -> end `"...09:30:00Z"`; start `"...11:00:00.000Z"` -> end `"...11:30:00.000Z"`.

**2. Enum routing — exhaustive closed list**, all 21 verified over HTTP as 400/`ERR_INVALID_ENUM`: `party_type`; pen `species_class`, `pen_type`; consignment `species_class`, `weigh_basis`, `yardage_basis`, `commission_basis`, `ration_type`; lot `livestock_class`, `bid_basis`; `bond_type`; `inspection_type`; manifest `haul_basis`, `proration_basis`; `to_status` on party-status / pen-status / crew-duty / pen-move-status / sale-day-advance; `result`; `loss_type`. **No other field routes here.** Deliberate exclusions verified: query filters never error (unknown value -> empty list); numeric range and missing fields -> `ERR_INVALID_REQUEST`; wrong-for-the-moment state -> `ERR_INVALID_STATE`; body FKs -> `ERR_REFERENCE_NOT_FOUND`; rung 4 outranks rung 5.

**3. EADDRINUSE** — socket pre-bound with `SO_REUSEADDR` in a 40x0.25s retry loop, fd handed to `werkzeug.serving.make_server`. **12 rounds of tight kill -9 + immediate relaunch: 0 start failures.** `start.sh` probes with `importlib.util.find_spec` and only installs when missing.

**Determinism:** ids are valid UUID strings whose high 32 bits are a monotonic counter, so ascending `id` == creation order (list ordering tie-breaks stably). This is id-minting, **not seeded data**.

## Twelve friction adjudications
1. **Yardage days** — one consignment-level count from the earliest-created lot's end instant (summing per-lot would multiply the stated formula). 2. **Zero lines** — all seven seller lines always written (incl. 0.00 FEED). 3. **Two settlements, one party** — both pour against the same untouched `balance_due` (PRD: the pour changes no balance). 4. **DOA memo** — `credit_memo_total` rises by the **supplied `amount`**; the computed credit lives on the purchase and its DOA line. 5. **Rung 43 cap** — `total_due - credit_memo_total` (PRD §3.11 states the reduction verbatim). 6. **Rung 20 denominator** — all tickets count, VOIDED/SUPERSEDED included. 7. **G5 reach** — rung-15 scope only (`settlements/{id}/release`), keeping void/payment/memo paths reachable. 8. **Void hop 3** — **any** existing settlement -> `ADJUSTED`, not only RELEASED. 9. **`loss_type`** — `DEAD`/`CONDEMNED`/`WITHDRAWN` per the PRD. 10. **Bid restoration** — only the two named triggers (revoke, purchase void); no restoration on no-sale or close. 11. **Governing ticket** — highest-seq CAPTURED on both bases. 12. **`max_draft_lb`/`head_on_draft`** — recorded, unpoliced.

## Bug found and fixed during verification
A `VOIDED` invoice was being reused as "the buyer's invoice for this sale day", leaving a later purchase permanently unbillable (never ISSUED -> never PAID -> lot could never clear the gate). `find_or_create_invoice` now looks past voided rows.

## Note on `money_reconciliation_ok`
Implemented verbatim. It closes exactly in every scenario without trucking. After a manifest dispatch it reports `false` by exactly the `HAUL` amount — the PRD's invariant includes every non-`DOA_CREDIT` charge line, while `total_due` (subtotal + buyer_fee - memos) has no haul term. That is a faithful reading of two pinned formulas, and the boolean is doing its declared job of surfacing the gap.

## Step 8: Finalize PRD — 2026-08-08T19:22:00.000Z

`PRD_FINALIZED.md` is written. One edit, one legitimate zero-edit item.

## Line counts
- `PRD.md`: 491 lines. `PRD_FINALIZED.md`: 491 lines. Delta: 0 lines (+0.0%); one line (302) rewritten in place, +661 characters.

## Changes
- **§3.9 (Trucking, the Trailer and the Gate) — revise** — pinned the source-status semantics of removing the last load line: only a manifest at `LOADING` reverts to `PLANNED`; a `DISPATCHED` manifest keeps `DISPATCHED` (no `DISPATCHED -> PLANNED` edge); totals and `haul_charge` fall to zero regardless of the resulting status; the `HAUL` charge line appended at dispatch is never deleted or re-amounted by a removal — `implementation/routes/manifests.py:145-152`, `implementation/services/manifests.py:22-32`, `implementation/services/charges.py:31-34`.

## Per-edit pre-edit search log

**Edit 1 — §3.9 load-line removal**
- (a) Subject: what `DELETE /sale-barn/load-manifests/{id}/lines/{line_id}` does per manifest source status, and whether it unwinds the dispatch-time `HAUL` charge line.
- (b) Impl paths enumerated and read: `routes/manifests.py` in full — `create_manifest` (initial `PLANNED`, zero totals, `haul_charge` 0.00), `add_line:108-127` (allowed statuses `PLANNED`/`LOADING`, `PLANNED -> LOADING` on first line, `recompute_manifest` after every add), `remove_line:131-153` (status guard `LOADING`/`DISPATCHED`; custody revert only when the lot is `LOADED`; `recompute_pens` only on that branch; reversion to `PLANNED` guarded by `status == "LOADING"` **and** no lines remaining; `recompute_manifest` unconditional), `dispatch:156-184` (the only writer of a `HAUL` charge line), `deliver`, `close_manifest` (all-lots-`RELEASED` check, vacuously true on an emptied manifest). `services/manifests.py` in full — `manifest_lines`, `haul_charge` (returns 0.00 when `loaded_head == 0`, so an emptied manifest zeroes the charge on any status), `recompute_manifest` (zeroes `loaded_head`/`loaded_weight_lb` when no lines), `prorate` (no-op with no lines). Grepped `HAUL|haul` across the whole impl to confirm no other creation/mutation site; grepped `charge_lines` for deletions — the only deletion is `services/charges.py:delete_settlement_lines`, keyed on `settlement_id`, and a `HAUL` line carries `settlement_id = None`, so settlement regeneration (voids/re-pricing) can never touch it.
- (c) Wording adjustments made: (i) scoped the reversion to "a manifest standing at `LOADING`" rather than restating an unconditional "the manifest reverts", so the `DISPATCHED` path is not mis-described; (ii) moved the zeroing of `loaded_head`/`loaded_weight_lb`/`haul_charge` out of the `PLANNED` clause and made it status-independent ("whatever the status ends up being"), because `recompute_manifest` runs on every removal, not only on the reverting one; (iii) wrote the `HAUL` claim as "a removal never deletes it and never re-amounts it" — scoped to removal only, so it does not accidentally forbid the dispatch-time creation or claim anything about settlement-line regeneration; (iv) dropped a drafted trailing clause pinning `ERR_INVALID_STATE` for other source statuses — accurate against `routes/manifests.py:142-143` but outside the Step 7 item's trace, so it was removed rather than committed.

## Zero-edit item
- **Item 2 (`adjustment_amount: -100.00`)** — no edit. PRD.md §2.7 rung 6 already determines it verbatim: "Numeric body fields satisfy their sign and range constraints — head counts at least 1, money amounts at least 0, `pencil_shrink_pct` at most 0.06, payment and adjustment amounts strictly greater than 0 | `ERR_INVALID_REQUEST` | 400". Verified against `implementation/routes/money_routes.py:203` (`check_min(v["adjustment_amount"], 0, "adjustment_amount", inclusive=False)`), and the test's re-derived expectations follow directly from §3.10's existing net formula and §3.11's "`adjustment_total` rises by the adjustment amount". Pure fixture bug.

## Step 9: Complete PRD — 2026-08-08T19:40:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Result

| | source `PRD_FINALIZED.md` | `PRD_COMPLETED.md` |
|---|---|---|
| lines | 491 | 504 (+13) |
| chars | 101,497 | 132,379 (**+30,882**) |
| `#` headings | 30 | 30 — **identical set, no section added** |

**48 changes: 33 ambiguity-pins, 15 mismatch-revisions.** Tables (rung ladder, endpoint table, error catalogue) kept byte-for-byte structurally intact — 168 table rows in both files.

### Changes

- §2.2 — insert — ambiguity — `api_request_id` shape; `api_request_timestamp` read from the **logical** clock — `envelope.py:14,20`
- §2.2 — insert — ambiguity — full field set always emitted incl. nulls; lean resources omit `updated_at`/`version` rather than nulling them — `serialize.py:287,342`
- §2.2 — insert — ambiguity — 204 carries no envelope; unrouteable path/405 -> `ERR_RESOURCE_NOT_FOUND`; unparseable/non-object body -> `ERR_INVALID_REQUEST`; absent body = `{}` — `app.py:45-54`, `bodyval.py:21`
- §2.3 — revise — **mismatch** — `limit`/`offset` are **clamped, never rejected**; unparseable falls back to default — `envelope.py:46-66`
- §2.3 — revise — ambiguity — list tie-break on **creation order**; `has_more` formula — `envelope.py:72,35`
- §2.3 — insert — ambiguity — filters compare raw strings; unknown value -> empty page, never an error; five resources have no list endpoint — `bodyval.py:8-12`
- §2.4 — revise — **mismatch** — version bumps per **mutation step, not per request** (payment bumps its invoice twice); unchanged rows are not touched — `store.py:60`, `routes/buyer_registrations.py:188,207`
- §2.4 — insert — ambiguity — clock echo verbatim; the three-case instant-rendering policy (server-minted / caller-echoed / derived-in-source-style); date fields — `clock.py:6-27,87,110`
- §2.5 — insert — ambiguity — discipline binds on derived figures only; supplied weights not re-rounded; `loaded_weight_lb` 2 dp; money renders `0.0` — `money.py:49-60`, `services/manifests.py:27`
- §2.6 G1 — insert — ambiguity — §3.1 furniture + clock + sale-day creation sit outside every gate — `routes/infrastructure.py`
- §2.6 G2 — revise — **mismatch** — G2 reaches only writes that name a lot; `dispatch`/`deliver`/`close` move lots without it — `routes/manifests.py:162,193,207`
- §2.6 G3 — insert — ambiguity — reach is exactly the rung-13 list; ticket void, move status, quarantine, inspections, registration writes stay open — `gates.py:19-33`
- §2.6 G4 — insert — ambiguity — exactly one owning party per endpoint, enumerated (bids/voids/memos key on the **bidding** party) — `routes/bids.py:44`, `routes/money_routes.py:50`
- §2.6 G5 / §2.7 — revise — **mismatch** — the rung-15 scope is operative: only `settlements/{id}/release` answers `ERR_SETTLEMENT_RELEASED` (**friction 7**) — `gates.py:37-46`
- §2.7 rung 6 — revise — ambiguity — the exhaustive per-field sign/range table + instant/date parse failures — across all route modules
- §2.7 — insert — ambiguity — the 16 further conditions that answer `ERR_INVALID_STATE` — across all route modules
- §2.9 — insert — ambiguity — `loss_type` vocabulary closed at three spellings (**friction 9**) — `config.py:136`
- §2.10 — insert — **mismatch** — all six invariants and all 15 sale-day roll-ups are **derived at read time**; the stored counters listed — `serialize.py:40`, `services/saleday.py:39`
- §2.11 — insert — ambiguity — per-type charge-line column shapes (incl. `INDEMNITY_FEE` head = 0, `HAUL` naming no invoice/lot) — `services/settlements.py:259-279`, `services/close.py:51`
- §2.11 — insert — ambiguity — settlement lines are **deleted and rewritten** on re-pricing; buyer-side lines never rewritten — `services/charges.py:31`
- §3.1 — insert — ambiguity — only `origin_state_code` is ever consulted on a party; same-status target -> `ERR_INVALID_STATE` — `routes/infrastructure.py:70`
- §3.1 — insert — ambiguity — `pen_type` never consulted — `services/pens.py`
- §3.1 — insert — **mismatch** — `max_draft_lb` recorded, never policed (**friction 12**); unparseable cert dates read `EXPIRED` — `routes/infrastructure.py:139`, `serialize.py:68`
- §3.1 — insert — ambiguity — crew clock-down guard answers `ERR_INVALID_STATE`; `member_count` never consulted — `routes/infrastructure.py:191`
- §3.2 — insert — ambiguity — `barn_code`/`reopen_count` never consulted; `sale_date` unparsed — `routes/sale_days.py:33`
- §3.2 — insert — ambiguity — any target outside the eight edges -> `ERR_INVALID_STATE` — `routes/sale_days.py:17-26`
- §3.3 — insert — ambiguity — booking requires `CHECK_IN_OPEN` — `routes/consignments.py:68`
- §3.3 — insert — **mismatch** — lot creation has **no consignment-status precondition** — `routes/lots.py:52-58`
- §3.3 — insert — **mismatch** — on the lot-withdrawal path `head` and `loss_type` are validated then **ignored**, rung 27 is skipped, and the lot need not belong to the consignment — `routes/consignments.py:149,180`
- §3.4 — insert — ambiguity — re-weigh denominator counts **all** tickets (**friction 6**); `head_on_draft` never consulted — `routes/weigh_tickets.py:57-63`
- §3.4 — insert — ambiguity — "governing prior captured ticket" = the governing ticket at capture time — `routes/weigh_tickets.py:114`
- §3.4 — insert — ambiguity — supersession is by strictly lower `ticket_seq`; one governing rule on **both** weigh bases (**friction 11**) — `services/lots.py:16-26`
- §3.5 — insert — ambiguity — `from_pen_id` may be null; `head_moved` never read; pen admission checked **only at booking**; unparseable start -> 400 before FK resolution — `routes/pen_moves.py:40,51,74`
- §3.6 — insert — **mismatch** — a record's own `destination_state_code` is **never consulted**; the lot's is — `services/inspections.py:46-52`
- §3.6 — insert — ambiguity — any one adequate record satisfies; result-edge errors — `services/inspections.py:22`, `routes/inspections.py:93-101`
- §3.6 — insert — ambiguity — rung 30 runs across **all** required types before rung 31 runs on any — `services/inspections.py:13-33`
- §3.7 — insert — ambiguity — `buyer_number` integer >= 1, uniqueness ignores status; `effective_limit` starts at 0 — `routes/buyer_registrations.py:33,43,58`
- §3.7 — insert — ambiguity — `effective_limit` stored, written only at approval and override — `services/buyers.py:15`
- §3.7 — insert — ambiguity — credit-hold's two edges only — `routes/buyer_registrations.py:108-115`
- §3.7 — revise — **mismatch** — the four exposure figures are derived on read, not "recomputed on events" — `services/buyers.py:45-51`
- §3.8 — insert — ambiguity — `bid_seq` counts every bid ever recorded on the lot — `routes/bids.py:83`
- §3.8 — insert — ambiguity — restoration fires on exactly two triggers, never at no-sale or close (**friction 10**) — `services/bidding.py:37-65`
- §3.8 — revise — **mismatch** — `PER_CWT` extension with no settle weight yields `0.00`, not "no figure" — `services/lots.py:71-77`
- §3.8 — insert — ambiguity — rung-8 match is lot vs the **bid's registration**, before OCC — `routes/lots.py:190-197`
- §3.8 — insert — ambiguity — hammer-down answers the created **Purchase** at 201; `VOIDED` invoices are never reused — `routes/lots.py:244`, `services/invoices.py:67-78`
- §3.9 — insert — ambiguity — lines only while `PLANNED`/`LOADING`; no lot-status or ownership check on addition; a weightless lot ends in `ERR_INVALID_REQUEST` — `routes/manifests.py:108-124`
- §3.9 — insert — ambiguity — proration zero-residual/zero-divisor guards and the created-order tie-break — `services/manifests.py:35-57`
- §3.9 — insert — ambiguity — rung 41 scans **all** the lot's lines; funds check reads only the **earliest unvoided purchase**; custody rung first — `routes/lots.py:307-348`
- §3.9 — insert — ambiguity — a line on a foreign manifest answers `ERR_RESOURCE_NOT_FOUND` — `routes/manifests.py:136`
- §3.10 — insert — ambiguity — hop 3's skipped set; hop 4 opens settlements only for consignments reconciled **in this run** — `services/close.py:36-40,62`
- §3.10 — revise — ambiguity — **all seven** seller lines always written including `0.00` (**friction 2**) — `services/settlements.py:215`
- §3.10 — revise — ambiguity — yardage day count taken from the **earliest-created lot**; no-check-in -> 1 day (**friction 1**) — `services/settlements.py:78-90`
- §3.10 — revise — ambiguity — a second settlement pours against the **same untouched** balances; zero/negative net pours nothing (**friction 3**) — `services/settlements.py:148-179`
- §3.10 — insert — ambiguity — the interposed step touches `DRAFT` invoices only — `services/close.py:43-46`
- §3.10 — revise — **mismatch** — roll-ups are not a cascade step; they are derived on read — `services/saleday.py:39`
- §3.11 — insert — **mismatch** — the payment's invoice need not belong to the addressed registration; posture rung first — `routes/buyer_registrations.py:177-185`
- §3.11 — insert — **mismatch** — the memo's purchase need not sit on the addressed invoice; must be `INVOICED`; no `doa_head` => plain memo — `routes/money_routes.py:88-102`
- §3.11 — revise — ambiguity — `credit_memo_total` rises by the **supplied amount** (**friction 4**); `subtotal`/`buyer_fee` untouched — `routes/money_routes.py:112-118`
- §3.11 — insert — ambiguity — void hop 3 drives **any** settlement to `ADJUSTED` (**friction 8**); hop 4 reuses the cached day count and never re-pours the offset — `services/voids.py:49`, `services/settlements.py:228`
- §3.11 — insert — ambiguity — `balance_ok` false -> `ERR_INVALID_STATE`; covering-invoice set definition — `routes/money_routes.py:179`, `services/settlements.py:284`
- §3.11 — revise — **mismatch** — `adjustment_amount` must be **strictly positive** (no negative adjustments); `reason` required then discarded — `routes/money_routes.py:203`
- §4 — insert — ambiguity — the four writes that answer something other than the addressed resource — `routes/lots.py:244`, `routes/manifests.py:128`, `routes/buyer_registrations.py:208`, `routes/infrastructure.py:31`

### Friction adjudications

`grep -rn "Adjudication of friction"` returns **11** sites, not 12 — frictions **1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12**; **there is no friction-5 comment anywhere in `implementation/`**. All 11 are now pinned in PRD_COMPLETED.md (mapped above). The one further deliberate reading recorded in a docstring rather than a friction comment — `find_or_create_invoice` looking past `VOIDED` invoices (`services/invoices.py:67`) — is pinned in §3.8 as well.

**Orchestrator independent verification (Steps 8/9):** friction 5 (rung 43's credit-memo cap) chased down and confirmed pinned despite having no `Adjudication of friction 5` comment — the impl comment at `routes/money_routes.py:104-108` explains that PRD §3.11 already stated the reduction verbatim, so no adjudication was needed; `cap = total_due - credit_memo_total` matches PRD_COMPLETED.md line 361 ("The memo may not exceed the invoice's `total_due` reduced by the credit memos already recorded in `credit_memo_total`"). `diff` of all `^#` headings PRD.md vs PRD_COMPLETED.md is **empty** — Step 9 added no sections. Line/char counts: PRD.md 491/101,080 -> PRD_FINALIZED.md 491/101,497 -> PRD_COMPLETED.md 504/132,379. `find implementation -newer results.1.json -name '*.py'` is **empty** — Steps 8 and 9 edited no implementation code, so the green sweep still describes the shipped tree. All 8 `results.N.json` present.

## PIPELINE COMPLETE — 86/86 x 8 rounds, 0 deletions, 0 implementation fixes.
