# Worklog — task_2551_liquidation_marketplace_bulk_lot_auctions

## Step 1: Create task directory — 2026-09-03T09:24:08.190Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2551_liquidation_marketplace_bulk_lot_auctions` and its `workspace/` subdirectory. Index 2551 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-03T11:19:02.285Z

All three scaffold artifacts for task 2551 are complete and the linter is clean.

Verdict block, verbatim from the final run of `python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py /home/ubuntu/github/CodingPRD/tasks/task_2551_liquidation_marketplace_bulk_lot_auctions`:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1261

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Artifacts (all under `/home/ubuntu/github/CodingPRD/tasks/task_2551_liquidation_marketplace_bulk_lot_auctions/`):
- `SCAFFOLD.yaml` — 3517 lines / 181 KB. §1.0–§1.7 only (top keys: scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles); no `scaffold_difficulty_design` / `scaffold_corner_design` key. 14 entities, 9 state machines, 2 OCC rules, 16 calculations, 57 validations (16 priority bands), 60 endpoints, 69 errors, 5 roles with two segregation-of-duties rules.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2485 lines / 160 KB. Single top-level key, 9 rule blocks × 2 instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5664 lines / 338 KB. Single top-level key, 75 instances across all nine guide sections (57 with full `test_recipe`, 18 `excluded_because` stubs): entities 11, state_machines 10, calculations 9, validations 9, endpoints 5, errors 18, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1.

Key findings during the final pass:
- One §1.5 fix was required to reach clean lint: the inline output schema of `GET /liquidation/recovery-analytics` listed bare field names, so the linter could only recover `groups` and rejected all 14 `$.data.gross_recovery_rate`-style captures. Typed every field in that flow mapping (`gross_recovery_rate: decimal`, etc.); the declared shape is unchanged. This was the sole root cause of all 14 violations.
- Corrected a design error found while writing the rate-threshold instance: `SaleOrder.payment_status` has no `LATE` value (UNPAID / PARTIALLY_PAID / PAID / REFUND_ISSUED only), so the late-fee sweep instance now asserts `late_fee_cents == 44805` with `payment_status` still UNPAID rather than inventing a fifth state.
- `ERR_PAYMENT_WINDOW_CLOSED` is a priority-10 ABANDONED-logistics gate, not a temporal one; the stub was renamed `paying_an_abandoned_order_returns_payment_window_closed` and re-grounded accordingly.
- Two errors are provably unreachable as returned ids and are documented as shadows rather than asserted: `ERR_LISTING_ALREADY_OPEN` (lot-state rule fires first) and `ERR_EVIDENCE_INSUFFICIENT` (priority-9 claim-state gate fires first, and any UNDER_REVIEW claim already has ≥2 evidence items).
- Self-audit beyond the linter: all 69 error ids appear in the two design files, 75 corner names are unique and disjoint from the 18 difficulty names, every `excluded_because` citation resolves to a real `<rule_id> / <instance_name>`, no stub carries a `test_recipe`, and 0 unbound `${var}` references across all setup/trigger/assert phases in both files.

## Step 3: Copy shared files — 2026-09-03T11:19:19.979Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:33:38.979Z

PRD generation and verification complete. No forbidden file was opened at any point: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, grepped, or referenced, and no sibling task directory under `/home/ubuntu/github/CodingPRD/tasks/` was touched. `SCAFFOLD.yaml` was the sole input.

**Output:** `workspace/PRD.md` — **444 lines**, built with 13 chunked `cat >>` appends (never a single giant Write), then two targeted repair edits.

### Hard Contract Reports

**Field coverage check: PASS.** 134/134 scaffold entity field names appear verbatim in backticks; 15/15 non-entity input identifiers (`expected_listing_version`, `expected_negotiation_version`, `decision`, `review_note`, `reversal_reason`, etc.) present; 69/69 `error_id` values present; 5/5 role names present. Zero missing. All 38 distinct state values across the 9 state machines appear as standalone backticked tokens (two repairs were required and applied: `CLOSED_SOLD`/`CLOSED_NO_SALE` in §3.3, and `SELLER` as an `offer_side` value in §3.5 — previously both existed only inside compound transition tokens or as substrings). The only ALL-CAPS scaffold identifiers absent from the PRD are the 22 internal constant *names* (`SNIPE_WINDOW_SECONDS`, `BUYER_PREMIUM_TIERS`, `UNITS_PER_PALLET`, `BUYER_NET_OUTLAY`, …), which is required by the no-pseudocode rule; every one of their literal values is stated in prose (120 seconds, five minutes, 1,400/1,200/1,000 basis points, 8,500 cents per pallet, 1 / 3 / 8 percent tolerances, 0.850, 0.2500, 2,000/1,500/2,500 bps).

**Rule coverage check: PASS.** All 16 validation priority bands are rendered as §2.5's ordered ladder and re-anchored inline at their point of use with explicit band numbers (bands 9→10→12→13→14→15 for freight booking; 9→10→11→12→15 for publication; band 5 segregation-of-duties ahead of every claim state check). All 42 state transitions across 9 state machines are expressed; the 7 with compound source states in the scaffold are written out branch-by-branch (e.g. `MANIFEST_APPROVED → LISTED` and `RELIST_PENDING → LISTED` separately; `APPROVED → REVERSED` or `PARTIALLY_APPROVED → REVERSED`). Both OCC rules give explicit 412 rejection semantics with no-side-effect guarantees. All 16 calculations are specified with normative rounding order, including the two dual-variant ones (PROVISIONAL/FINAL settlement, GROSS/NET recovery) and the two order-sensitive one-cent divergences. Cross-entity cascades, sibling-negotiation auto-decline symmetry, the two one-directional cross-dimension guards on `payment_status`×`logistics_status`, field-level defaults (`turnaround_buffer_minutes` 15, tier `TIER_STANDARD` at 2,000 bps, `manifest_accuracy_avg` 1.000), both sweeps, and both segregation-of-duties rules are all in prose.

**Path purity check: PASS.** 915 backticked tokens in §3 scanned; 0 `/`-leading tokens, 0 bare HTTP methods, 0 method+path combinations. Also 0 unbackticked `/`-leading path tokens. Paths appear only in §1 (the `/liquidation` mount note), §2.4 (`POST /_clock/set_current_utc`), §2.7 (the two OCC write endpoints), and §4's table.

**§2.2 is byte-identical** to `section-2.2-response-structure.md`. **§4** has exactly 60 rows, one per scaffold endpoint, zero missing. **§5** has exactly 69 rows, one per scaffold error, zero missing. No audit footer was written into PRD.md or any sibling file.

### Document ends at a real section boundary

The file ends on a completed §5 Error Code Catalogue table row, not mid-sentence. Last 5 lines verbatim:

```
| `ERR_PROXY_MAX_BELOW_MINIMUM` | 422 |
| `ERR_FIXED_PRICE_MISMATCH` | 422 |
| `ERR_OFFER_BELOW_MINIMUM` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
```

### Section headings in order

1. `# Liquidation Marketplace Bulk Lot Auctions API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 Participants, Headers and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 Resource Identity, Timestamps, Versions and the Logical Clock; 2.5 Validation Precedence: Sixteen Ordered Bands; 2.6 Money, Rates, Ratios and Rounding Discipline; 2.7 Optimistic Concurrency on Bidding and Negotiation; 2.8 Cascade Discipline: One Write, Many Rows; 2.9 Nested Paths and Sub-Resource Read Channels; 2.10 Reference Data and Uniqueness
4. `## 3. Business Logic & Workflows` — 3.1 Building a Lot and Getting Its Manifest Approved; 3.2 Qualifying a Buyer: Certificates, Verification and Credit Headroom; 3.3 Offering the Lot: Format Choice, Brand Protection and Publication; 3.4 The Auction Floor: Live Bids, Hidden Ceilings and Anti-Sniping; 3.5 Three Ways a Lot Changes Hands; 3.6 The Money Waterfall: Premium, Freight, Payment and Late Fees; 3.7 Freight: Dock Windows, Doors, Completion and Abandonment; 3.8 Manifest Discrepancy Claims: Evidence, Refunds and Reversal; 3.9 Seller Standing, Commission Tiers, Payouts and Recovery Analytics
5. `## 4. Endpoint Definitions` (60-row table: Method | Path | Description | Authorized Role(s))
6. `## 5. Error Code Catalogue` (69-row table: Error ID | HTTP Status Code)

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — `wc -l` = 444, `wc -c` = 109166, `tail -15` ends on the final `| \`ERR_PAYMENT_EXCEEDS_BALANCE\` | 422 |` catalogue row at a real section boundary, and `grep '^#'` shows all six top-level/§ sections present through §5. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T13:15:34.138Z

Suite is complete. Final state of the two output directories:

**`test_helpers/`** — 9 files, 2,302 lines (unchanged this session): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`** — `conftest.py` + 13 test files, 5,834 lines, **94 tests**, all collected cleanly by pytest (`94 tests collected`), every file `py_compile`-clean.

Work completed in this final stretch:
- Wrote `test_13_rbac_and_identity.py` (7 tests, 612 lines) covering the 6 `Corner/rbac/*` instances plus `Corner/errors/unknown_path_and_body_ids_return_their_not_found_errors`: the five cross-role 403s (with TrustSafety's closure on an unknown listing id proving band 2 beats band 3), the SellerOps ownership gate across three writes plus the analytics read (with the owner's identical calls succeeding), Buyer ownership outranking `ERR_PAYMENT_EXCEEDS_BALANCE` and `ERR_ORDER_NOT_PAID`, the reviewer-cannot-decide duty split (403 then `ops-claims-9` approving 8 units → refund 95,040 / total 2,891,960 / wallet 95,040 / lot 1.000), the decider-cannot-reverse split (403 under the TrustSafety role, then `ts-2` restoring claim_credit 0 / total 2,987,000 / wallet 0), empty `X-User-ID` beating both the 404 and the enum error, and the six path-id 404 families plus two body-FK 404s.
- **Deliberate PRD-first omission:** the design's `seller_id`-in-body and `buyer_id`-in-body 404 probes were dropped. On `POST /lots` and `POST /listings/{id}/bids` an unresolvable owner id also violates band 4 (`ERR_NOT_RESOURCE_OWNER`, which precedes band 6), so the PRD does not uniquely derive `ERR_SELLER_NOT_FOUND` / `ERR_BUYER_NOT_FOUND` there. `ERR_BRAND_POLICY_NOT_FOUND` and `ERR_CARRIER_NOT_FOUND` (no ownership overlap) are asserted instead.

Both mandatory audit passes now green:
- **PRD-citation pass:** 273 quotes across 13 files, all verbatim (whitespace-normalized substring of `PRD.md`) and all section labels resolving to the section that actually contains them. This pass caught and fixed 8 pre-existing defects: a dropped `§` in five quotes (`clamp of §3.6` ×2, `as §3.9 specifies` ×2, `rule of §2.1`), a misquoted §3.8 APPROVE/PARTIALLY_APPROVE sentence in file 10 (the PRD omits "the claim"), a nonexistent `PRD 2.11:` label in file 04 (→ `2.10`), and a wrong `PRD 3.5:` label on the exposure sentence in file 13 (→ `3.2`).
- **Scaffold-citation pass:** 94/94 tests carry exactly one trailing `Design:` line, all 94 tags resolve; 36 difficulty tests = exactly 2 per each of the 18 §1.8 instances; 58 corner tests cover 57/57 non-stub §1.9 instances, and none of the 18 `excluded_because` stubs was tested.

No `skip`/`xfail`/TODO markers, no duplicate test names, no reference to the implementation directory (never read), `__pycache__` removed.

## Step 6: Generate implementation — 2026-09-03T13:15:34.138Z

Implementation complete and verified. Final state:

**Location** `workspace/implementation/` — 3,434 lines across 22 Python modules plus `start.sh` (`exec python3 app.py`, guarded pip install, `PORT` env, binds `0.0.0.0`) and `requirements.txt` (`flask>=2.0`).

**Structure**
- `app.py` — blueprint registration, `strict_slashes = False`, `ApiError`/HTTPException/catch-all handlers, a global `threading.RLock` around every request, no seeding of any kind.
- `util.py` (logical clock at epoch `2026-08-01T00:00:00Z`, Decimal ROUND_HALF_UP helpers), `response.py` (envelope, pagination, bare arrays for sweeps), `errors.py` (~70 error ids → HTTP codes), `middleware.py` (headers, roles, shape validators), `db.py` (14 in-memory dicts, wire-shape `FIELDS`, `touch`/`touch_soft`).
- `services/`: `calc`, `aggregates`, `orders` (waterfall, per-line payout freeze, `settle_final`), `bidding` (proxy resolution, anti-sniping), `logistics` (dock-door interval merge + buffer, carrier day capacity), `guards`, `lookups`.
- `routes/`: `reference`, `lots`, `listings`, `bids`, `negotiations`, `orders`, `claims`, `ops`.

**Endpoint parity** A programmatic diff of the Flask url_map against every `method`/`path` pair in `SCAFFOLD.yaml` reports zero missing and zero extra routes (60 endpoints), and each returns the scaffold's declared status code (201 only for true creations; `evidence-items`, sweeps, transitions and computed reads are 200).

**Runtime verification** (server launched on an ephemeral free port, killed by PID resolved from `ss`, never a pattern-kill) — three smoke scripts ran the full domain end to end with zero unexpected status codes, reproducing the PRD's normative worked examples exactly:
- refund arithmetic → `refund_cents` 950,400 on the 100×40,000 line / 2,700,000 hammer / 1,000 bps example;
- per-line commission summation → 405,000 with `seller_net_proceeds_cents` 2,295,000, `gross_recovery_rate` 0.2700, `net_recovery_rate` 0.2295;
- late fee → 44,678 on a 2,978,500 pre-fee total (half-up on .5), assessed once, sweep idempotent on re-run;
- accuracy scoring → 0.708 on a 250-unit `CUSTOMER_RETURNS` lot with 73 units of excess, seller flipped to `MANIFEST_PROBATION`/2,500 bps, and reversal restored score `null`, avg 1.000, `scored_lot_count` 0, `TIER_PREFERRED` — true compensation with the order back to `PAID` at `claim_credit_cents` 0 and wallet credit unwound;
- dock doors → 14:00–15:00 on door 1 forces a 15:00 start to door 2 under the 15-minute buffer, cancellation frees the interval, a 15:15 start reuses door 1, and carrier day capacity refuses the third same-day booking;
- proxy bidding → sole proxy prices at the opening bid, second proxy lands at `min(leader_max, runner_up + increment)`, a bid inside the last 120s extends `effective_close_at` by 300s and increments `extension_count`; stale `expected_listing_version` → 412;
- negotiation → floor rejection, `ERR_NOT_YOUR_TURN` on an out-of-turn counter, 48h offer TTL, acceptance producing a `NEGOTIATED_ACCEPTANCE` order with the listing `CLOSED_SOLD` and lot `SOLD`;
- pickup-deadline sweep abandons overdue orders (lot → `RELIST_PENDING`, exposure and seller aggregates recomputed), is idempotent, and payment afterwards returns 409 `ERR_PAYMENT_WINDOW_CLOSED`;
- analytics `NONE`/`CATEGORY`/`CHANNEL` grouping, plus 403 when a `SellerOps` caller names another seller.

**Fresh-boot check** After killing and relaunching, all list endpoints return `total_count: 0`, a newly created row stamps `created_at: 2026-08-01T00:00:00.000Z` (logical clock at epoch, never wall-clock), and unauthenticated reads return 401 — so per-test reboots start from a clean, unseeded process. A grep audit confirms no `sqlite`, `json.dump`, file `open(`, `pickle` or `/tmp` usage anywhere; state is pure in-memory dicts. No server processes of mine remain listening.

## Step 7: Run tests and iterate — 2026-09-03T13:34:05.137Z

All 8 parallel rounds are green (94/94 each). Final sweep results live in `workspace/implementation/results.{1..8}.json`.

**Iterations run:** 3 full 8-round parallel sweeps (sweep 1: 90/94, sweep 2: 93/94, sweep 3: 94/94).

**Final per-round passed/total (last sweep, read from the results files):**
- results.1.json — 94/94 · results.2.json — 94/94 · results.3.json — 94/94 · results.4.json — 94/94
- results.5.json — 94/94 · results.6.json — 94/94 · results.7.json — 94/94 · results.8.json — 94/94
- 0 failed, 0 errors, 0 skipped in every round; ~170 s per round.

**Tests deleted:** none. Every failure traced to a test-side defect that PRD prose uniquely resolves, so all 94 tests were kept and corrected (STEP 2 outcomes, not STEP 1 deletions).

**Fixes applied to `test_helpers/`:** none — the failures were all in `test_suite/` assertions/constants, not in fixtures or factories.

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_claims_and_accuracy.py`, module constant `VOIDED_LINE` — `declared_condition` was `"USED_FAIR"`, which is outside the PRD §2.10 enum (`NEW`, `LIKE_NEW`, `USED_GOOD`, `DAMAGED`, `SALVAGE`); the PRD-faithful implementation correctly returned `ERR_INVALID_REQUEST` at band 7 and the whole setup chain of `test_the_filing_gate_refuses_five_different_ways_and_writes_nothing` aborted. Changed to `"DAMAGED"`.
- `test_suite/test_10_claims_and_accuracy.py`, `test_reversing_the_claim_restores_the_buyer_net_outlay_with_no_drift` — asserted post-reversal `manifest_accuracy_score == 1.000`, `verified_unit_count == 0`, `scored_lot_count == 1`. PRD §2.8 ("every field the decision moved returns to the value it held before the decision — … the lot's accuracy score, the seller's average, scored lot count …") plus §3.8 ("stays null until the first claim against it is resolved") and §3.1 (`verified_unit_count` starts null) make the pre-claim values `None`, `None`, `0`. Corrected to those, with the citations inlined.
- `test_suite/test_13_rbac_and_identity.py`, `test_the_deciding_operator_cannot_reverse_its_own_approval` — same post-reversal score assertion; changed `== 1.000` to `is None`.
- `test_suite/test_05_auction_bidding.py`, `test_the_outbid_proxy_keeps_its_ceiling_hidden_and_each_write_bumps_the_version` — two mis-translations: (a) asserted the proxy row's `amount_cents == 2_700_000`, but PRD §3.4 pins it to "the resolved public price **at the moment of placement**", i.e. `min(3,000,000, 1,000,000 + 100,000) = 1,100,000`; (b) asserted `bid_count == 3`, but PRD §3.4 counts only `STANDING`/`WINNING`/`WON`/`LOST`, and the challenger's first bid is `SUPERSEDED`, so the count is 2. Both corrected, and the nested-min coverage the test exists for was strengthened by asserting the listing's `current_high_bid_cents == 2_700_000`, `current_high_bidder_id`, and `min_next_bid_cents == 2_800_000` (all PRD-verbatim derivable).

**Fixes applied to `implementation/`:** none. No implementation defect was found — every failing assertion contradicted a verbatim PRD sentence that the implementation already honoured (proxy `amount_cents` placement snapshot, `bid_count` status set, reversal-as-true-compensation returning the lot score / line verified units / scored-lot count to their pre-decision nulls and zero).

No `skip`/`xfail` was added, no `error_id` assertion was downgraded, and no PRD-required implementation check was weakened.

**Orchestrator verification of the sweep artifacts (per the known "claimed clean sweep with no artifacts" failure mode):** independently re-read all eight `results.$i.json` files on disk (each ~28.8 KB, all timestamped 13:32). Every round reports `passed=94 total=94 failed=0 errors=0 skipped=0`. Confirmed green; no re-run needed.

**Step 8 gate decision:** Step 7 did NOT exit on the first sweep — 3 iterations were run and 4 `test_suite/` fixes were applied. The skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is therefore not met, so Step 8 runs. Note that all four fixes were test-side mis-translations of PRD prose the implementation already honoured, so Step 8 is expected to find few or no genuine PRD silences at these sites; it must patch only where PRD failed to uniquely determine what the implementation does.

## Step 8: Finalize PRD — 2026-09-03T13:38:47.206Z

Done. Three edits to `PRD_FINALIZED.md`; two Step 7 items needed no PRD change.

### Line counts
- `PRD.md`: 444 lines / 109,166 bytes
- `PRD_FINALIZED.md`: 444 lines / 110,062 bytes
- Delta: 0 lines (+0.0%), +896 bytes (+0.82%) — three in-paragraph clarifications, no new sections.

### Changes
- **§3.4 (Auction Floor, ¶1)** — revise — pinned that a proxy bid's `amount_cents` is the `current_high_bid_cents` the listing publishes *after* the resolution has run with the new proxy already in the pool (not the pre-placement price), applies whether or not the proxy leads, and is a never-rewritten snapshot — `implementation/routes/bids.py:161-162`.
- **§3.8 (Scoring the manifest, ¶1)** — revise — pinned that `manifest_accuracy_score` is null exactly while no claim against the lot's lines stands `APPROVED`/`PARTIALLY_APPROVED`, so a reversal that empties the population returns it to null rather than a recomputed 1.000 — `implementation/services/aggregates.py:27-37`.
- **§3.8 (The ledger effect, last sentence)** — revise — pinned that `ManifestLine.verified_unit_count` comes from the `verified_units` of the most recently decided `APPROVED`/`PARTIALLY_APPROVED` claim on that line and goes back to null when none remains, and that a reversal re-derives the same chain — `implementation/services/aggregates.py:40-55`, `implementation/routes/claims.py:130-135, 249-250`.

**No edit** for two Step 7 items:
- `VOIDED_LINE` `declared_condition = "USED_FAIR"` — pure fixture bug; §2.10's enum (`NEW`, `LIKE_NEW`, `USED_GOOD`, `DAMAGED`, `SALVAGE`) is byte-identical to `middleware.py:21`, and band-7 rejection is already PRD-verbatim.
- `bid_count == 2` and the strengthened nested-min assertions (`current_high_bid_cents == 2_700_000`, `min_next_bid_cents == 2_800_000`) — §3.4 already pins the counted status set and both formulas verbatim, and `services/bidding.py:23-27, 56-63, 89-92` matches verbatim.

### Per-edit pre-edit search log

**Edit 1 — subject: `Bid.amount_cents` (all writers/readers, both bid types).**
(b) Enumerated: `routes/bids.py:42` (live payload amount), `:71-81` (auction live row), `:90-100` (fixed-price live row, `WON`), `:149-162` (proxy row, `None` then post-`resolve` assignment), `services/bidding.py:38-94` (`resolve` reads `amount_cents` only for a *sole LIVE* candidate; never writes it), `close_auction` `routes/bids.py:190-246` (rewrites `bid_status` only), `db.py:125-129` (`bid` view field list — no derivation); grepped `amount_cents` repo-wide to confirm the only other users are `Offer.amount_cents` and payment amounts (`routes/negotiations.py`, `routes/orders.py`), which are unrelated entities.
(c) Adjustments: scoped the sentence to proxy bids only (left live-bid semantics untouched), added "whether or not the new proxy ends up leading" so the non-leading-proxy branch (`amount_cents` = another buyer's resolved price) is not mis-described, and said "never rewritten by later bids or by the closure" rather than "equals the leader's price", since `resolve`/`close_auction` never touch `amount_cents`.

**Edit 2 — subject: `Lot.manifest_accuracy_score` (every writer).**
(b) Enumerated via repo-wide grep: `routes/lots.py:58` (creation → `None`), `services/aggregates.py:27-37` (sole recomputation), its two callers `routes/claims.py:221` (APPROVE/PARTIALLY_APPROVE only — `DENY` and `REQUEST_EVIDENCE` return at `:199/:207` before the chain) and `:250` (reversal), reader `services/aggregates.py:105-119` (seller average population), `services/calc.py:105-119` (`accuracy_score` never returns `None`; returns 1.0 when `declared_unit_count <= 0`), `services/lookups.py:175-179` (`claims_of_lot` spans all lines of the lot, including `VOIDED` ones — matching PRD's unfiltered "every claim against a manifest line of this lot").
(c) Adjustments: phrased as "no claim against any of that lot's manifest lines" (not "active lines") to stay consistent with `claims_of_lot`'s lack of a `line_status` filter; kept the existing "recomputed on every claim decision" clause verbatim rather than narrowing it to approving decisions, since on `DENY` the recomputation would be a no-op anyway and narrowing risked contradicting §2.8's accuracy chain.

**Edit 3 — subject: `ManifestLine.verified_unit_count` (every writer).**
(b) Enumerated: `routes/lots.py:116` (line append → `None`), `routes/lots.py` void-line path (recomputes the three lot aggregates only; never touches `verified_unit_count`), `services/aggregates.py:40-55` (sole recomputation; orders the `APPROVED`/`PARTIALLY_APPROVED` claims by `_decided_seq`, i.e. decision order, and `db.touch`es the line only when the value actually changes), `routes/claims.py:130-135` (chain), callers `:221` (decision) and `:250` (reversal), `routes/claims.py:22-27, 217` (`_decided_seq` assigned only on approve/partial-approve), `db.py:115` (line view field).
(c) Adjustments: replaced the ambiguous "non-reversed decision" gloss with the explicit `APPROVED`/`PARTIALLY_APPROVED` status set, because a `DENIED` claim is also a non-reversed decision yet the impl never lets it write `verified_unit_count` (early return, no accuracy chain); used "most recently decided" rather than "latest filed" to match `_decided_seq` ordering; said "re-derives all three the same way" instead of naming pre-claim values, so the multi-claim case (another approval still standing) is not mis-described.

**Orchestrator verification:** `PRD_FINALIZED.md` exists, is 444 lines / 110,062 bytes, is NOT byte-identical to `PRD.md` (+896 bytes), and ends on the completed §5 error-catalogue table — so the file was genuinely patched rather than merely copied.

## Step 9: Complete PRD — 2026-09-03T14:08:35.241Z

**Orchestrator decision (recorded per the AUTONOMY rule):** Step 9 was run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, rather than one monolithic scan. Rationale: the implementation is 3,425 lines across 22 modules, and a single subagent asked to walk all of it exhaustively while also holding a 447-line PRD tends to degrade into a plain `cp` with a plausible-sounding summary (the known failure signature is `PRD_COMPLETED.md` coming out byte-identical to its source). Partitioning by implementation file gives each pass a tractable surface and makes the byte-count growth per pass independently checkable. Pass A owned the global/reference/lots layer and performed the initial `cp`; Passes B and C edited the same file in place and were explicitly told which sections earlier passes had already pinned, so they would neither duplicate nor contradict them.

### Pass A — app/util/response/errors/middleware/db/helpers/reference/lots/lookups/guards

`cp PRD_FINALIZED.md PRD_COMPLETED.md` performed. Before edits: 444 lines / 110,062 bytes. After: 447 lines / 117,528 bytes (the 3 added lines are new rows in the §5 error table; everything else in-paragraph). **18 ambiguity-pins, 4 mismatch-revisions** (22 line-level edits / 21 diff hunks).

- §2.1 — revise — mismatch — dropped the false "401 before the path is resolved" claim; an unrouted path answers `ERR_NOT_FOUND` (404) and an unrouted method `ERR_INVALID_REQUEST` (400) regardless of headers; header values trimmed; any non-role spelling is 403 — app.py:46-54, middleware.py:30-41
- §2.10 — revise — mismatch — `brand_code` carries **no** uniqueness constraint (only seller tax_id, buyer tax_id, SCAC are enforced) — routes/reference.py:225-250
- §3.1 — revise — mismatch — manifest line takes its lot from the path `{id}`; a body `lot_id` is only existence-checked at band 6 and otherwise ignored — routes/lots.py:94-120
- §4 (qualification-decisions row) — revise — mismatch — `business_verified` is required only for `QUALIFY` from `PENDING`; reinstatement from `SUSPENDED` needs only the unexpired certificate — routes/reference.py:138-149
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase/digit chars, on error responses too — util.py:127, response.py:17-21
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — response.py:20, util.py:83
- §2.2 — insert — ambiguity — sweep arrays carry `response_type` `array` with no pagination fields in `meta` — response.py:51-58
- §2.3 — insert — ambiguity — non-integer/empty `limit`/`offset` → 400 (leading `+` tolerated); offset past the end yields an empty page with `has_more` false — response.py:73-100, 42
- §2.3 — insert — ambiguity — `created_at` ties are broken by creation sequence, never by `id` — db.py:74-76
- §2.4 — insert — ambiguity — client instants accepted with/without seconds, fraction and offset; `Z`/offset normalised to UTC, naive treated as UTC; dates must be exactly `YYYY-MM-DD` — util.py:34-69
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at creation — db.py:36-47
- §2.5 band 3 — insert — ambiguity — added the missing 404 ids: warehouse/carrier/brand-policy, `ERR_OFFER_NOT_FOUND`, and the generic `ERR_NOT_FOUND` for an unresolved **bid** id — services/lookups.py:16-69
- §2.5 band 7 — insert — ambiguity — non-JSON / non-object body → 400, absent body = `{}`, `null` behaves as omitted, undeclared members ignored, integers must be JSON ints (bools rejected); the five payload-free operations never read the body at all — middleware.py:45-136
- §2.8 — insert — ambiguity — a row changed only by derived-aggregate recomputation refreshes `updated_at` but not `version` — db.py:61-71
- §2.9 — insert — ambiguity — filters are exact-match and conjunctive, unmatched values give an empty page, an empty value matches null fields, unknown query params are ignored — routes/helpers.py:9-27
- §2.10 — insert — ambiguity — brand-policy defaults (false / 0 / empty array / null embargo, no ordering check) and that all reference strings are stored verbatim with no length or format validation — routes/reference.py:180-248
- §2.10 — insert — ambiguity — `requested_credit_limit_cents` defaults to 0, may not be negative — routes/reference.py:80
- §3.1 — insert — ambiguity — lot-creation `seller_id` must equal `X-User-ID`, compared at band 4 *before* existence (403 beats 404); omitting it is 400 — routes/lots.py:25-41
- §3.1 — insert — ambiguity — void returns the manifest line (not the lot), bumps the line's version, and re-voiding an already-`VOIDED` line is accepted — routes/lots.py:147-158
- §3.2 — insert — ambiguity — reinstatement checks only certificate expiry; `REJECT` on a `SUSPENDED` buyer is a state error — routes/reference.py:118-149
- §5 — insert — ambiguity — table rows for `ERR_OFFER_NOT_FOUND` (404), `ERR_NOT_FOUND` (404), `ERR_INTERNAL` (500) plus an intro clause on the two transport-level fallbacks — errors.py:33/97, app.py:46-68

Left unpatched deliberately: the request-serialization lock, `strict_slashes=False`, and JSON key ordering in app.py (no observable contract); `whole_seconds_between`'s sub-second truncation (consumer is in pass B/C territory); `DEFAULT_MESSAGES` wording; credit-limits accepting a buyer in any qualification state; `review_note` being ignored (PRD never claims it is persisted).

### Pass B — listings/bids/negotiations/bidding/calc

447 lines / 117,528 bytes → 447 lines / 123,276 bytes. All in-paragraph; Pass A's edits untouched. **20 ambiguity-pins, 3 mismatch-revisions.**

- §3.3 — insert — ambiguity — listing creation gates nothing on `lot_status` (any state, `DRAFT` included); owning lot comes from the path, a body `lot_id` is band-6 existence-checked then ignored — routes/listings.py:26-32
- §3.3 — insert — ambiguity — `opening_bid_cents`/`ask_price_cents`/`min_offer_cents`/`reserve_price_cents` floor at **zero** (zero accepted, negative 400); only `bid_increment_cents` floors at 1 — routes/listings.py:48-54
- §3.3 — insert — ambiguity — a half-open embargo (one endpoint null) is unbounded on the missing side; and the publication gate never compares the offering window to the clock, so a future-start or already-expired window publishes normally — routes/listings.py:124-134, 137-166
- §3.3 — insert — ambiguity — publication returns the updated `Listing` — routes/listings.py:177
- §3.4 — insert — ambiguity — live-bid payload: `amount_cents` ≥ 1 cent; body `buyer_id` is band-4 ownership *before* band-6 existence, omission is band-7 — routes/bids.py:20-42
- §3.4 — insert — ambiguity — proxy payload: same `buyer_id` treatment, `max_amount_cents` ≥ 1 cent — routes/bids.py:120-123
- §3.4 — insert — ambiguity — band 9 also admits by format: live bid needs AUCTION/FIXED_PRICE, proxy needs AUCTION, negotiation opening needs NEGOTIATED; mismatch is `ERR_LISTING_STATE_INVALID` — routes/bids.py:47-48,130; routes/negotiations.py:36
- §3.4 — insert — ambiguity — prospective exposure *replaces* the buyer's own active bids on that same listing with the new ceiling (other listings/orders still count) — services/aggregates.py:160 via routes/bids.py:66
- §3.4 — revise — **mismatch** — tie-break was "creation time is the sole tie-break"; impl breaks equal `created_at` by creation sequence — services/bidding.py:30-35
- §3.4 — revise — **mismatch** — "every other candidate remains STANDING" → an ex-leader is demoted back to `STANDING` keeping its last `meets_reserve`; leader's `meets_reserve` is re-snapshotted every resolution (can fall to false); non-fresh candidates advance `version` on status/flag change, the freshly created bid stays at `version` 1 — services/bidding.py:74-88
- §3.4 — insert — ambiguity — whole seconds remaining is **truncated toward zero** — services/bidding.py:103 / util.py:99
- §3.5 — insert — ambiguity — closure on a non-`OPEN` or non-`AUCTION` listing is band-9 `ERR_LISTING_STATE_INVALID`; takes no payload — routes/bids.py:190-198
- §3.5 — insert — ambiguity — either closure outcome returns the updated `Listing`, not the order — routes/bids.py:226,246
- §3.5 — insert — ambiguity — a fixed-price sale leaves `current_high_bid_cents`/`current_high_bidder_id`/`reserve_met`/`min_next_bid_cents` exactly as they stood (high-bid fields stay null) while `bid_count` is recounted; response is the created `Bid` at 201 — routes/bids.py:90-112
- §3.5 — insert — ambiguity — negotiation opening: both fields required, `opening_offer_cents` ≥ 1 cent, same band-4/band-6 `buyer_id` treatment — routes/negotiations.py:28-33
- §3.5 — insert — ambiguity — the credit admission on an opening runs against exposure **as it already stands** (offer amount not added), so it can only fail for a buyer already past its ceiling — routes/negotiations.py:56
- §3.5 — insert — ambiguity — counter `amount_cents` ≥ 1 cent — routes/negotiations.py:116
- §3.5 — revise — **mismatch** — "Four conditions govern a counter" was a closed set; impl additionally requires at band 10 that the *negotiation's buyer* be `QUALIFIED` whichever side acts (`ERR_BUYER_NOT_QUALIFIED`) — routes/negotiations.py:129-130
- §3.5 — insert — ambiguity — counter returns the updated `Negotiation`; the appended `Offer` is found via the offers list — routes/negotiations.py:165
- §3.5 — insert — ambiguity — acceptance's whole gate is state + turn + expiry + band-4 ownership: no qualification re-check, no geographic re-check, no payload, and no `Offer` appended — routes/negotiations.py:170-181
- §3.5 — insert — ambiguity — acceptance advances the listing's own `version` by one — routes/negotiations.py:198
- §3.5 — insert — ambiguity — acceptance returns the updated `Negotiation` — routes/negotiations.py:208
- §4 — insert — ambiguity — nested `GET /lots/{id}/listings` accepts only `listing_status` and `listing_format`; `resale_channel` is ignored there — routes/listings.py:117-121

Deliberately left unpatched: `close_auction`'s no-sale lot guard (unreachable divergence); `calc.py` degenerate-input guards (`line_share_cents` on zero retail value, `accuracy_score` on non-positive declared units, `pallet_count(0)`) — all unreachable given manifest-submission preconditions; `calc.py` constants and the four money/ratio formulas (already pinned verbatim by §3.6/§3.8/§3.9); the §4 offers-row filter wording (§2.9 already pins the full filter set).

### Pass C — orders/claims/ops/orders-service/aggregates/logistics

447 lines / 123,276 bytes → 447 lines / 129,046 bytes. All in-paragraph. **11 ambiguity-pins, 3 mismatch-revisions.**

- §3.6 (settlement variants) — insert — ambiguity — `actual_freight_cents` (and `paid_at`/`picked_up_at`/`abandoned_at`/`claim_window_closes_at`) are null while the basis is `PROVISIONAL` — services/orders.py:38
- §3.6 (settlement variants) — insert — ambiguity — the `PROVISIONAL→FINAL` flip writes no `payment_status`: a `PAID` order stays `PAID` when higher actual freight re-opens `balance_due_cents`, that residual is unpayable (payments admit only `UNPAID`/`PARTIALLY_PAID`) yet still makes the order late-fee-sweep eligible — services/orders.py:88-96 + routes/orders.py:52
- §3.6 (Paying) — insert — ambiguity — the 1..balance range test is band 16, so zero/negative `amount_cents` is `ERR_PAYMENT_EXCEEDS_BALANCE` (422), not a band-7 error — routes/orders.py:58
- §4 (preamble) — insert — ambiguity — sweep arrays are ordered `created_at` ascending with creation-sequence tie-break, and both sweeps visit candidates in that order — routes/ops.py:24,61
- §3.7 (booking gate) — insert — ambiguity — the requested window need not lie in the future; and at band 6 `warehouse_id` resolves before `carrier_id` — routes/orders.py:82-90
- §3.7 (completion) — insert — ambiguity — `picked_up_unit_count` required and non-negative (band 7, 400), otherwise unconstrained versus `declared_unit_count`; no upper temporal bound, so completion after `window_end_at` is accepted — routes/orders.py:165-172
- §3.7 (completion) — insert — ambiguity — the response carries only the updated `PickupAppointment`, not the order — routes/orders.py:187
- §3.7 (cancellation) — insert — ambiguity — a buyer cancelling after the window opened is `ERR_APPOINTMENT_STATE_INVALID`; `MarketplaceOps` is not time-bound; response is the appointment — routes/orders.py:203,214
- §3.8 (filing) — insert — ambiguity — `claimed_units` below 1 is band-7 `ERR_INVALID_REQUEST`; `evidence_urls` is an array of strings defaulting to empty and is not persisted (no `evidence_urls` field on the claim); `filed_at == created_at` — routes/claims.py:46,47,77
- §3.8 (deciding) — revise — **mismatch** — `DENY` accepts an omitted `verified_units` as zero (PRD had said "exactly zero"); omission on `APPROVE`/`PARTIALLY_APPROVE` is a mismatch; negative fails band 7 first; `REQUEST_EVIDENCE` ignores the field — routes/claims.py:169,191
- §3.8 (decision outcomes) — insert — ambiguity — `REQUEST_EVIDENCE` leaves `verified_units` and `decided_by_user_id` untouched — routes/claims.py:196
- §3.8 (ledger effect) — revise — **mismatch** — recency is decision order; the manifest line's `version`/`updated_at` move only when `verified_unit_count` actually changes, while the lot's `version` advances on every approval/partial/reversal that reaches scoring — services/aggregates.py:40-55, routes/claims.py:134
- §3.8 (reversal) — insert — ambiguity — a reversal rewrites only `claim_status` and `reversed_by_user_id`, retaining `refund_cents`/`verified_units`/`decided_by_user_id`; a second reversal is `ERR_CLAIM_STATE_INVALID` — routes/claims.py:243
- §3.9 (analytics read) — insert — ambiguity — missing/empty `seller_id` is 400 and is tested ahead of band-4 ownership and band-6 existence; `group_by`/`category_code`/`resale_channel` are enum-validated (400) *after* ownership and seller existence; `resale_channel` keeps lots with ≥1 listing on that channel and orders whose own listing carries it; order population is always restricted to orders on surviving lots — routes/ops.py:113-141
- §3.9 (analytics grouping) — revise — **mismatch** — `CHANNEL` groups take the lots having ≥1 listing on the key plus orders whose listing's `resale_channel` is the key (a two-channel lot counts in both); keys ascending alphabetical and only keys the population exhibits — routes/ops.py:153,168

Deliberately left unpatched: band-7 internal field ordering (unobservable — one shared `ERR_INVALID_REQUEST`); the exposure formulas in `services/aggregates.py` (already verbatim in §3.2); `freeze_seller_payout`'s `policy is None` branch (unreachable — a lot without a brand policy gets `de_branding_required=False`); row-`version` bumps that follow mechanically from §2.8; `_clock/set_current_utc` response shape (already pinned by §2.4).

Pass C's stated confidence: moderate-to-high that no material residual silence remains in its six files; whole-implementation confidence necessarily lower since it could not re-verify Pass A/B territory. The one cross-pass boundary it touched — §2.8's general claim about a manifest line's `version` — was refined locally in §3.8 rather than by editing §2.8, so the two read as general rule plus local refinement rather than a contradiction.

### Totals and orchestrator verification

- `PRD.md` 444 lines / 109,166 bytes → `PRD_FINALIZED.md` 444 lines / 110,062 bytes → `PRD_COMPLETED.md` **447 lines / 129,046 bytes** (+18,984 bytes / +17.4% over PRD.md).
- Aggregate across the three passes: **49 ambiguity-pins, 10 mismatch-revisions** (59 edits), no new sections, +3 lines (all §5 error-table rows).
- Verified `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran, not a bare `cp`) and ends at a real section boundary — final line is the completed `| \`ERR_INTERNAL\` | 500 |` catalogue row.
- Verified no file under `workspace/implementation/` was modified after the green sweep (`find -newermt '2026-09-03 13:33'` returns nothing), so the Step 7 result — 8/8 rounds at 94/94, 0 failed / 0 errors / 0 skipped — remains valid for the delivered implementation. Steps 8 and 9 touched documentation only.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` is written.
