## Step 1: Create task directory — 2026-08-14T16:54:00.000Z

Task directory `tasks/task_1795_farmland_auction_brokerage/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command; Step 1 treated as DONE (no index scan, no new directories).

## Step 2: Generate scaffold — 2026-08-14T18:04:00.000Z

Scaffold generation complete for task_1795_farmland_auction_brokerage. No sibling task directories were read — the design was derived purely from the scenario text plus the skill spec.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Summary
- **Entities: 13** — Seller, BrokerAgent, Buyer, Listing, Tract, ComparableSale (immutable, `common_fields: false`), AuctionEvent, Bid, EarnestMoneyDeposit, LeaseDisclosure, RightsDisposition, ClosingPackage, SettlementStatement.
- **Endpoints: 42** (25 writes incl. `POST /api/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`, 17 reads). This exceeds the ~28–32 guideline deliberately: the lint's FK reverse-reachability rule (f) forces one single-resource GET per FK parent plus one filtered/sub-resource GET per FK, and the 13-entity Expert surface carries 11 FKs; I trimmed to the minimum that keeps every FK reachable and every state testable (no suspend/resume or withdraw-bid endpoints; sealed reveal folded into the close sweep).
- **State machines: 10**, non-linear highlights: AuctionEvent `OPEN ⇄ EXTENDED` soft-close self-loop; ClosingPackage with three parallel axes (title × survey × funding) + title exception cure loop + computed `overall_status`; Listing `MARKETED → AUCTION_SCHEDULED → MARKETED` re-list cycle; Buyer `QUALIFIED → EXPIRED → QUALIFIED`; EMD deadline machine (PENDING → LATE → FORFEITED) driving a depth-5 cascade.
- **Difficulty instances: 18 (2 per rule × 9)**, all with fully-structured replayed chains and pre-computed literal asserts, e.g. valuation PROVISIONAL 833333 vs APPRAISAL 924373; net sheet PROVISIONAL 1136000.00 vs FINAL 1133380.60; commission 31900.00 with 110%-of-appraisal kicker; per-tract allocation 5038.30/2361.70 summing to exactly 7400.00 with residual-to-highest-tract_number; cascades depth 5 (EMD forfeit) and depth 3 (listing withdraw); priority pairs state-vs-fiscal and safety-vs-temporal; boundaries on money increment (>=) vs empty-bid-set auto-NO_SALE; cross-entity gates Bid→Buyer and ClosingPackage→LeaseDisclosure; overlap rules half-open-adjacency (Listing) vs 2h-buffer (BrokerAgent); conserved acreage and conserved escrow dollars.
- **Corner instances: 41 entries** — 38 active (entities 5, state_machines 6, calculations 4, validations 12, endpoints 1, rbac 4, cross_cutting 5, incl. both OCC stale-version 412 tests) + 3 `excluded_because` stubs citing difficulty instances.
- **Errors: 29** (all referenced by ≥1 validation/transition, all triggerable by ≥1 instance). **Concurrency rules: 2** (OCC on `AuctionEvent.version` for bids, `Listing.version` for tract adds), both passing §1.2.1's serial-observability filter.

## Checklist / lint results
- Call-by-call replay and end-state replay done for every chain in both design files (all version captures re-read after version-bumping side effects; all literals pre-computed by hand-executing the formulas).
- Mechanical audits: forbidden race vocabulary — none; top-level key split — correct; instance-name uniqueness across both files — 60 unique; all `grounds:` resolve; error catalog fully cross-referenced; enum closure verified; selector determinism pins `created_at ASC` tie-break (no `id` usage anywhere).
- `scaffold_lint.py` final verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    42
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  948

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(Two intermediate lint failures were fixed en route: unquoted `$.data[0].*` JSONPaths and flow-style `grounds:` lists broke YAML parsing — both mechanical formatting, no design changes; plus one stub that incorrectly cited a corner instance instead of a difficulty instance was removed.)

## Step 3: Copy shared files — 2026-08-14T18:05:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1795_farmland_auction_brokerage/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T18:22:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/workspace/PRD.md`.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/workspace/PRD.md` — 317 lines, ends at §5 with no audit footer.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (headers, 4 roles, identity prose per role), 2.2 API Response Structure (verbatim block, byte-identical incl. `req_RANDOMALPHANUM123456` and `"data": { }`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (incl. `ComparableSale` exception: only `id`/`created_at`), 2.5 Logical Clock & Scheduled Sweeps (default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, sweep inventory), 2.6 Monetary Precision & Rounding (pinned rounding orders), 2.7 OCC (both rules, exact error ids + 412), 2.8 Validation Order & Nested Retrieval (10-step priority pipeline, left-to-right 404), 2.9 Cascading State Consistency
- §3 Business Logic (8 subsections): 3.1 Onboarding & Qualification, 3.2 Listing/Tracts/Packaging, 3.3 Comparables & Valuation, 3.4 Disclosures/Rights/Marketing, 3.5 Auction Scheduling/Opening/Soft-Close, 3.6 Bidding, 3.7 Award/EMD/Forfeiture Cascade, 3.8 Closing/Statements/Disbursement
- §4 Endpoint table (4 columns × 42 endpoints), §5 Error catalogue (2 columns × 29 errors)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 66 required, 66 present, 0 missing
- endpoints[].request_body/query_params/path_params + common fields: 15 required, 15 present, 0 missing
- (combined set: 81 required, 81 present, 0 missing)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: global 10-step pipeline in §2.8 plus explicit per-endpoint orderings (bids §3.6, packaging §3.2, auction creation §3.5, closing creation §3.8, tract creation §3.2) — all expressed, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_listing_version/expected_auction_version + ERR_STALE_LISTING_VERSION/ERR_STALE_AUCTION_VERSION + HTTP 412), 0 missing
- state_machines[].transitions: all 10 machines (Listing, Tract, AuctionEvent, Bid, Buyer, EMD, LeaseDisclosure, RightsDisposition, ClosingPackage incl. parallel axes + CURE/WAIVE/DISBURSE, SettlementStatement) fully expressed with preconditions→error ids and side effects, 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (valuation both variants, increment tiers, winner selection, EMD max($10,000, 3%), commission tiers+kicker+floor, cost allocation with per-tract-first rounding and residual to highest tract_number, net sheet pinned pipeline, possession proration with daily-rate-first rounding), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error ids in §2/§3 prose (all 29 catalog errors appear in prose), 0 missing
- endpoints[].side_effects / applies_to: all 42 endpoints' side effects narrated; ERR_DUPLICATE_RECORD enumerated across all 6 applies_to endpoints; ERR_AUCTION_WINDOW_INVALID across create+open, 0 missing
- entities[].fields[] structured content: defaults/initials/nullability reconstructible (soft-close/extension default 5, extension_count 0, awarded_total null pre-award, EMD zero-fields, tract_allocations null for PROVISIONAL, acknowledged_by_buyer_id null until acknowledged, axis initials), 0 missing
- sibling-branch symmetry: withdraw ×4 states, cancel ×3, terminate ×3, forfeit ×2, verify ×2, award winners from PLACED/REVEALED, VOIDED ×4 sources, close sweep OPEN/EXTENDED — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 600
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 emitted byte-identical to the canonical source; zero fuzzy/approximating words; all enum/state values (70+) present as exact strings; no pseudocode operators in prose; the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directories were read.

## Step 5: Generate unit tests — 2026-08-14T18:57:00.000Z

## Summary — task_1795_farmland_auction_brokerage test generation

### Test counts per queue
- **Queue A (Difficulty, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 34 tests** — 17 of 18 instances × 2 tests each (≥2 target met for every translated instance).
- **Queue B (Corner, `SCAFFOLD_CORNER_DESIGN.yaml`): 38 tests** — 38 of 38 non-stub instances × 1 test each. The 3 `excluded_because:` stubs (`error_auction_not_open_on_closed_auction`, `withdraw_cascade_side_effects`, `earnest_forfeiture_deadline_mechanics`) were not translated; their `difficulty_instance` cross-references all resolve to real queue-A instances.
- **Total: 72 tests**, all collecting cleanly under `pytest --collect-only`.

### Instances skipped (with reason)
- **`Difficulty/combinatorial_formula/commission_tiered_marginal_plus_kicker`** — fails the PRD-first unique-derivability filter. The instance asserts `commission == 31900.00` for gross 590000, but PRD §3.8's tier schedule ("4.5 percent of the portion above $250,000 up to $750,000") yields base 15000 + 15300 = 30300 and, with the kicker firing, **33250.00**. The instance's own decomposition (15000+11250+2700) applies 4.5% to only 250000 of the 340000 in tier 2, and its appraisal figure (533988) also diverges from the PRD formula result (533888) for the described data. A PRD-faithful implementation would fail the asserted values, so the instance was skipped per the Core rule — not weakened, not marked skip/xfail.

### Setup corrections (assertions untouched)
Three design recipes had internally inconsistent setup numbers that would fail at the packaging reserve floor before reaching the asserted behavior; fixtures use corrected reserves so the PRD-pinned assertions stand: soft-close/withdraw flows (tract SPI 60 → provisional 540000 → floor 459000) use reserve 460000 instead of 430000/750000; the parallel-axes flow uses the standard 770000/770000 bid-reserve pair.

### `test_helpers/` (Stage 1)
`/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/test_helpers/`:
`__init__.py` (barrel), `types.py` (13 entity TypedDicts — `ComparableSale` correctly omits `updated_at`/`version` per PRD §2.4 — plus 17 status/role enums), `api_client.py` (35 endpoint methods), `api_errors.py` (28 error ids + HTTP map registered with the framework), `assertions.py` (per-entity asserters + `assert_instant_equal` (format-tolerant instant compare), `assert_money`, `assert_escrow_conservation`), `factories.py` (14 payload factories), `constants.py` (PRD thresholds + standard comparable sets), `test_users.py` (TEST_USERS + per-instance `make_*_headers` builders for the three entity-backed roles), `fixtures.py` (tiered composites: parties/qualification, comparables, listing assembly with auto-OCC version threading, `setup_marketed_listing`, `setup_open_auction`, `setup_awarded_whole`, `setup_awarded_combination`, escrow pay/verify, `drive_to_ready_to_close`, `setup_closing_ready`).

### `test_suite/` (Stage 2)
`conftest.py` + 7 files: `test_01_listings_packaging_valuation.py` (17), `test_02_auction_scheduling.py` (6), `test_03_bidding.py` (12), `test_04_auction_lifecycle.py` (7), `test_05_escrow_and_qualification.py` (5), `test_06_cascades.py` (9), `test_07_closings_statements.py` (16).

### Self-audit results
- **Stage 1**: all helper modules compile; package imports cleanly.
- **Stage 2 coverage**: every difficulty instance has ≥2 tags except the documented skip; every non-stub corner instance has exactly ≥1 tag; stubs have 0 tests.
- **Tag hygiene**: 0 untagged tests, 0 dual-tagged tests, 0 tags pointing to non-existent instances.
- **PRD citation pass**: 105 quoted citation segments across 72 docstrings, all verified verbatim against `workspace/PRD.md` (whitespace-normalized literal containment; 3 initial failures from missing `**` emphasis markers were fixed).
- **No `pytest.mark.skip` / `skipif` / `xfail` anywhere.**
- **Two-reader sweep**: timestamp assertions compare parsed instants (not string equality); `tract_allocations` asserted by `tract_id` lookup rather than list position (PRD pins no ordering); initial `version == 1` assertion dropped from the listing-creation test (PRD pins presence/type, not the initial value); sealed-bid amount-null asserted via GET reads (the PRD-pinned surface), not the create echo.

## Step 6: Generate implementation — 2026-08-14T18:58:00.000Z

Implementation complete for task_1795 (Farmland Auction & Brokerage).

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/workspace/implementation/`)

- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask importable), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, blueprint registration, envelope-shaped 404/405/500 handlers
- `db.py` — in-memory store (13 dicts keyed by id) + logical clock starting at exactly `2026-08-01T00:00:00Z`; **no seeding anywhere** — a fresh boot is provably empty
- `errors.py` — `ApiError` + all 29 catalog error IDs with their HTTP statuses
- `response.py` — success/error envelopes (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`), Decimal-safe numeric coercion, strict-but-tolerant ISO 8601 parsing, `touch()` (updated_at + version bump on every mutation)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, four roles, 401/403 helpers
- `serializers.py` — per-entity JSON shapes (ComparableSale correctly omits `updated_at`/`version`; SEALED bid amounts serialize as `null` until REVEALED)
- `routes/` — `clock.py`, `parties.py`, `listings.py`, `auctions.py`, `escrow.py`, `compliance.py`, `closings.py`
- `services/` — `valuation.py` (PROVISIONAL/APPRAISAL comps math with 24/12-month calendar windows), `bidding.py` (tiered increments, combo premium, winner selection), `settlement.py` (marginal commission + kicker + floor, per-tract cost allocation with residual to highest tract_number, possession proration with pinned daily-first rounding), `sweeps.py` (auction close/no-sale, qualification expiry, EMD late/forfeit, full cascades)

## Endpoint count

**42 endpoints** — the complete scaffold endpoint table (clock, parties, listings/tracts/package/market/withdraw, comparables, valuation, auctions/open/award/no-sale, bids, deposits, disclosures, rights, closings/track-events/statements/terminate).

## Self-check results

- **Syntax:** `py_compile` clean on all 14 modules.
- **Boot smoke:** fresh `bash start.sh` → HTTP 200 within 3 s; repeated kill/relaunch cycles boot cleanly with empty state (verified `total_count: 0` and clock default `2026-08-01T00:00:00.000Z` on a fresh process).
- **Functional smoke (113 checks):** full happy path — onboarding, duplicate license 409, OCC 412s on tracts/bids, acreage mismatch, valuation math (PROVISIONAL 1,536,000 / APPRAISAL 1,728,000 verified by hand), packaging at the exact 85% reserve floor, rights/duplicate gates, auction window + open rules, bid increment tiers and OUTBID ripple, close sweep, award with EMD creation, segregation-of-duties (agent verify → 403), disclosure acknowledgement ownership, closing gates, provisional/final statement figures (commission 76,650; costs 9,175 with allocations summing exactly; rent credit 13,216.42), FINAL supersedes PROVISIONAL, duplicate FINAL 409, disburse cascade to CLOSED/PAID/APPLIED_TO_CLOSING/POSSESSION_TRANSFERRED.
- **Cascade/edge smoke (130 checks):** sealed-bid confidentiality (null amounts in read + list), one-sealed-bid-per-buyer, reveal sweep, forfeiture cascade (LATE at due, FORFEITED at due+24h, buyer DISQUALIFIED, bid VOIDED, auction NO_SALE, listing MARKETED, tracts OFFERED, rights DECLARED, DISQUALIFIED re-qualify rejected), zero-bid NO_SALE fallback, seller withdraw cascade, termination cascade (REFUNDED/VOIDED/NO_SALE/MARKETED/SUPERSEDED), ONLINE soft-close double extension (`effective_end` advanced correctly).

One judgment call worth flagging: the axis event vocabulary for `track-events` is underdetermined by the PRD (only `CURE` and `WAIVE` are named), so the transition tables accept the obvious verb forms plus target-state aliases (e.g. `ORDER`, `RECEIVE_COMMITMENT`/`COMMITMENT_RECEIVED`, `CLEAR`/`CLEARED`, `RAISE_EXCEPTION`/`EXCEPTION_RAISED`, `RECEIVE_FUNDS`/`FUNDS_RECEIVED`, `DISBURSE`); unknown events for the current axis state return `ERR_INVALID_CLOSING_STATE`.

## Step 7: Test iteration — 2026-08-14T19:05:00.000Z

### Iteration 1
- Sweep 1 (8 parallel rounds): 65/72 in every round — 7 deterministic failures, all in `test_07_closings_statements.py`, all sharing one setup error: `ERR_INVALID_CLOSING_STATE - event ORDER_COMMITMENT is not valid for TITLE in NOT_ORDERED`.
- Diagnosis (STEP 0-3): every failing test asserts PRD-verbatim rules (title-axis walk, overall_status derivation, commission/allocation/rent-credit figures, disburse cascade — docstring quotes verified against PRD.md §3.8). Coverage + unique derivability hold for the asserted outcomes. The only underdetermined element is the track-event request vocabulary: PRD §3.8 names only `CURE` and `WAIVE` ("an `event` naming the transition"). The fixtures' choices (`ORDER_COMMITMENT`, `CURE_EXCEPTION`) are PRD-consistent namings; deleting the tests would gut coverage of PRD-pinned settlement math, and no PRD-named vocabulary exists to relax to for the title-order transition. The Step-6 implementation had already chosen permissive aliasing (verb forms + target-state aliases) but missed the two aliases the fixtures use.
- Fix (implementation): `routes/closings.py` TITLE_EVENTS — added `ORDER_COMMITMENT` (NOT_ORDERED -> ORDERED) and `CURE_EXCEPTION` (EXCEPTION_RAISED -> COMMITMENT_RECEIVED) aliases. Same transitions, broader accepted labels; no PRD-required check weakened.
- Sweep 2 (8 parallel rounds): 72/72 in all 8 rounds. DONE.

## Step 7: Run tests and iterate — 2026-08-14T19:12:00.000Z

## Summary

**Final state: all 8 parallel rounds pass — 72/72 in every round.**

- **Iterations run:** 2 (sweep 1: 65/72 × 8 rounds; fix; sweep 2: 72/72 × 8 rounds).

- **Tests deleted:** none. Every failing test asserted PRD-verbatim rules (§3.8 title-axis walk, `overall_status` derivation, commission tier math, per-tract cost allocation, rent proration, disburse cascade — docstring PRD quotes spot-verified against `workspace/PRD.md`), so coverage and unique derivability held for all asserted outcomes.

- **Fixes applied to `test_helpers/`:** none. The fixtures' track-event vocabulary (`ORDER_COMMITMENT`, `CURE_EXCEPTION`, `RECEIVE_COMMITMENT`, `CLEAR`, `RAISE_EXCEPTION`, `WAIVE`, `ORDER`, `COMPLETE`, `RECEIVE_FUNDS`, `DISBURSE`) is consistent with PRD §3.8's "an `event` naming the transition" — PRD pins only `CURE` and `WAIVE`, so no fixture choice violates the PRD.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** one file, one table —
  `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/workspace/implementation/routes/closings.py`, `TITLE_EVENTS`: added `ORDER_COMMITMENT` as an alias for the `NOT_ORDERED → ORDERED` transition and `CURE_EXCEPTION` as an alias for the PRD-named `CURE` transition (`EXCEPTION_RAISED → COMMITMENT_RECEIVED`). The track-event vocabulary is underdetermined by PRD (only `CURE`/`WAIVE` named), and the implementation's existing design already accepted verb forms plus target-state aliases — it had simply missed the two aliases the tests use. Same transitions, broader accepted labels; no PRD-required check weakened, no capability added beyond the PRD-described endpoint.

**Failure signature (for the record):** all 7 failures were one root cause — `Setup step failed with HTTP 409: ERR_INVALID_CLOSING_STATE - event ORDER_COMMITMENT is not valid for TITLE in NOT_ORDERED` — hitting every test that drives a closing through `fixtures.drive_to_ready_to_close` or posts title-axis events inline (`test_net_sheet_provisional_variant_figures`, `test_net_sheet_final_variant_diverges`, `test_closing_cost_allocation_per_tract_shares`, `test_closing_cost_allocations_sum_exactly_to_total`, `test_title_cure_loop_cycles`, `test_axes_independent_until_ready`, `test_disburse_completes_full_close_cascade`). Deterministic across all 8 rounds, matching the triage-hint pattern of one upstream vocabulary gap masquerading as many failures.

## Step 8: Finalize PRD — 2026-08-14T19:16:00.000Z

The diff is exactly one localized change in §3.8. Final sanity check: my new paragraph's wording against the enumerated paths.

- **Verb + target-status alias framing:** accurate for every transition except survey `WAIVE` (target `WAIVED` is not an accepted event string) and funding `DISBURSE` (target `DISBURSED` is not accepted) — the hedge "for most transitions" covers both without falsely universalizing.
- **Per-state pairing:** each alias is listed under its exact source state, so no path (e.g., `CLEAR` from `ORDERED`, which the impl rejects) is mis-described as accepted.
- **WAIVE consent:** the untouched prior sentence still pins `WAIVE`-requires-`seller_consent: true` as `ERR_VALIDATION`, matching `closings.py:196–197` firing before the table lookup. My paragraph doesn't reorder or contradict that.
- **Rejection error:** "not accepted for the axis's current state" → `ERR_INVALID_CLOSING_STATE` matches `closings.py:208–211`; CLOSED/TERMINATED sentence preserved verbatim, matching lines 199–201.
- **`_derive_overall` and the disbursement gates** consume only status fields, so aliasing is invisible there — no wording needed.

Done. Summary:

**Line counts / %-delta**
- `PRD.md`: 317 lines; `PRD_FINALIZED.md`: 319 lines; **+2 lines (+0.63%)** — one paragraph split plus one inserted paragraph, single hunk.

**Changes**
- §3.8 (Closing Coordination — track events paragraph) — revise+insert — split the coordination paragraph after the funding-axis walk sentence and inserted a new paragraph pinning the exact accepted `event` strings per (axis, current-state) pair, mirroring the impl's transition tables verbatim: title `ORDER`/`ORDER_COMMITMENT`, `RECEIVE_COMMITMENT`/`COMMITMENT_RECEIVED`, `RAISE_EXCEPTION`/`EXCEPTION_RAISED` (from both `ORDERED` and `COMMITMENT_RECEIVED`), `CLEAR`/`CLEARED`, `CURE`/`CURE_EXCEPTION`; survey `ORDER`, `WAIVE`, `COMPLETE`/`COMPLETED`; funding `RECEIVE_FUNDS`/`FUNDS_RECEIVED`, `DISBURSE`; and re-stated that any non-accepted event string is `ERR_INVALID_CLOSING_STATE` — `implementation/routes/closings.py:32–58` (tables), `:196–211` (consent check, terminal guard, lookup rejection).

**Per-edit pre-edit search log** (one edit total)
- (a) Subject: accepted `event` vocabulary of `POST /api/closings/{id}/track-events` and its rejection error.
- (b) Paths enumerated: `closings.py:32–58` (TITLE_EVENTS/SURVEY_EVENTS/FUNDING_EVENTS), `:175–186` (endpoint, `as_enum` axis validation, free-string `event`), `:190–193` (duty split), `:196–197` (WAIVE consent, schema-tier), `:199–201` (CLOSED/TERMINATED guard), `:203–211` (table lookup → `ERR_INVALID_CLOSING_STATE`), `:213–232` (disbursement gates + cascade, keyed on status not event name), `:75–83` (`_derive_overall`, status-only). Repo-wide greps over `implementation/` and `test_helpers/` for all event strings, table names, and the route confirmed no other consumer (only stale `results.*.json` artifacts matched).
- (c) Wording adjustment: phrased aliases per (state, transition) pair rather than as a flat per-axis set (so e.g. `CLEAR` is not implied valid from `ORDERED`), and hedged the alias pattern with "for most transitions" since `WAIVE`→`WAIVED` and `DISBURSE`→`DISBURSED` have no target-status alias.

## Step 9: PRD completeness scan — 2026-08-14T19:35:00.000Z

The completed PRD is coherent. Final verification of stats and the produced file is done. Here is the summary.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1795_farmland_auction_brokerage/workspace/PRD_COMPLETED.md`

**Size delta:** source `PRD_FINALIZED.md` (319 lines, 53,046 chars) → `PRD_COMPLETED.md` (320 lines, 56,645 chars); +1 line, +3,599 chars, 21 edited passages.

**Counts:** 19 ambiguity-pins (inserts), 8 mismatch-revisions — 27 pinned points total.

### Mismatch revisions (PRD described behavior impl does not exhibit)

- **§2.8 step 4** — revise — mismatch — blanket "soil productivity … at most 100" scoped to tracts only; comparable SPI has no upper bound — `implementation/routes/listings.py:278` vs `:113-115`.
- **§2.8 step 4** — revise — mismatch — "a qualification expiry not in the future" applies only to re-qualification from `EXPIRED`, not initial qualification — `implementation/routes/parties.py:88-89`.
- **§3.1** — revise — mismatch — "records verbatim" → records the supplied instant normalized to UTC (impl reformats via `fmt_dt`) — `implementation/routes/parties.py:91`, `implementation/response.py:24-28`.
- **§3.2** — revise — mismatch — dropped "two-letter `state_code`"; no length/format constraint is enforced — `implementation/routes/listings.py:49`.
- **§3.2** — revise — mismatch — `tract_number` uniqueness within the listing is not enforced (duplicate numbers accepted) — `implementation/routes/listings.py:108,129-138`.
- **§3.4** — revise — mismatch — rights lock on "the listing's *first* auction opens" → *whenever* an auction of the listing opens, every `DECLARED` disposition locks — `implementation/routes/auctions.py:153-158`.
- **§3.5** — revise — mismatch — every auction creation increments the listing's `version` (touch is unconditional), not only the MARKETED→AUCTION_SCHEDULED transition — `implementation/routes/auctions.py:114-116`.
- **§3.7** — revise — mismatch — forfeiture voids *every* `CONFIRMED_WINNER` bid of the auction, not just the forfeiting buyer's — `implementation/services/sweeps.py:79-83`.

### Ambiguity pins (PRD silent; pinned to impl)

- **§2.3** — insert — creation-timestamp ties break by insertion order; `has_more` = `offset + returned < total_count` — `implementation/response.py:51,97-102`.
- **§2.4** — insert — `created_at`/`updated_at` read the logical clock (never wall time); `version` starts at 1 — `implementation/response.py:236-248`.
- **§2.5** — insert — clock-set accepts any instant; no monotonicity check — `implementation/routes/clock.py:21-23`.
- **§2.6** — insert — integral JSON numbers serialize without a fractional part (`100`, not `100.00`) — `implementation/response.py:223-229`.
- **§2.8 step 3** — insert — bid placement also resolves the caller's own buyer record from `X-User-ID` (absent → `ERR_NOT_FOUND`) — `implementation/routes/auctions.py:267`.
- **§2.8 step 4** — insert — datetime lexical rules: full ISO 8601 datetime required (bare date rejected), naive read as UTC, all datetimes normalized to UTC with 3 fractional digits — `implementation/response.py:189-216`.
- **§3.1** — insert — initial (UNVERIFIED) qualification has no future-check; qualifying a `QUALIFIED` or `DISQUALIFIED` buyer is `ERR_VALIDATION` — `implementation/routes/parties.py:84-89`.
- **§3.2** — insert — `reserve_price_total` accepted without any floor at creation — `implementation/routes/listings.py:52`.
- **§3.2** — insert — packaging a non-`DRAFT` listing → `ERR_INVALID_LISTING_STATE` — `implementation/routes/listings.py:170-171`.
- **§3.3** — insert — comparable field bounds: `sale_price_total` > 0, `tillable_acres` ≥ 0 and ≤ gross — `implementation/routes/listings.py:273-278`.
- **§3.3** — insert — missing/unrecognized `variant` → `ERR_VALIDATION`; month arithmetic preserves time-of-day with day clamping — `implementation/routes/listings.py:300-302`, `implementation/services/valuation.py:20-26`.
- **§3.4** — insert — lease start/end dates are not cross-validated — `implementation/routes/compliance.py:47-50`.
- **§3.4** — insert — `ERR_RIGHTS_LOCKED` check fires before the listing-state gate — `implementation/routes/compliance.py:125-132`.
- **§3.4** — insert — marketing a non-`PACKAGED` listing → `ERR_INVALID_LISTING_STATE` — `implementation/routes/listings.py:200-201`.
- **§3.5** — insert — soft-close/extension minutes accepted as any integer; soft-close window inclusive of the instant exactly `soft_close_window_minutes` before `effective_end` — `implementation/routes/auctions.py:64-65,368-370`.
- **§3.6** — insert — clock ≥ `effective_end` on an OPEN/EXTENDED auction is `ERR_AUCTION_NOT_OPEN`; duplicate `tract_ids` collapsed before scope evaluation; `OUTBID` ripple fires only for single-tract scopes — `implementation/routes/auctions.py:282-283,295,348-353`.
- **§3.7** — insert — escrow payment `amount` must be positive; forfeiture leaves other winners' deposits untouched; rights unlock per §3.4 when no active auction remains — `implementation/routes/escrow.py:32`, `implementation/services/sweeps.py:90-102`.
- **§3.8** — insert — statements are created by the listing's agent (else `ERR_FORBIDDEN`); either variant needs an APPRAISAL valuation per winning-scope tract (empty comparable set → `ERR_NO_COMPARABLES`); TITLE/SURVEY track events require broker ownership; `tract_allocations` ordered by first appearance across winning bids in creation order, residual ties on `tract_number` break toward the earlier entry; termination also unlocks rights per §3.4 — `implementation/routes/closings.py:285,303,181-182,403`, `implementation/services/settlement.py:29-41,86-88`.
- **§5** — insert — unrouted paths and unsupported methods surface `ERR_NOT_FOUND` (404); added `ERR_INTERNAL` (500) catalogue row — `implementation/app.py:24-38`.

No sections were added or removed; all changes are inline inserts/revisions. Areas verified already-pinned and consistent (no change): all endpoint role lists and the §4 table, envelope/meta shapes, ComparableSale's reduced common fields, sealed-bid null amounts, validation pipeline order per endpoint (state → OCC → compliance → temporal → referential → fiscal), 404 left-to-right nested retrieval, all calculation rounding orders (valuation, increments, EMD 3%-then-floor, commission tiers→kicker→floor, allocation per-tract-then-residual, proration daily-then-multiply, net sheet), sweep trigger boundaries (strict `>` for late/forfeit, `<= due_at` for RECEIVED), and all cascade status writes per entity.
