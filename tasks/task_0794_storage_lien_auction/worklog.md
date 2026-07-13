# Worklog — task_0794_storage_lien_auction

Scenario: Self-Storage Lien Auction Marketplace (StorageTreasures style): defaulted-unit lien process & notice, auction listing (online/onsite) & bidding, buyer registration & deposit, winning & cleanout deadline, payment & sales-tax, surplus/overage to tenant, facility settlement, dispute

## Step 1: Task directory — 2026-07-07 (pre-assigned)

Used pre-assigned folder tasks/task_0794_storage_lien_auction as-is (Step 1 directory scan skipped). Created workspace/ subdirectory.

## Step 2: Generate scaffold (Expert) — 2026-07-07

All three artifacts complete, parse cleanly (yaml.safe_load OK on all 3), pass scaffold linter (VERDICT: clean lint; 40 endpoints, 10 entities, 496 calls scanned; 13 FKs reverse-reachable).

Entities: 10 — Facility, Tenant, StorageUnit, LienNotice, Auction, Buyer, Bid, Sale, Settlement, Dispute (flat topology, 13 FKs).
Endpoints: 40 (22 POST actions + 18 GET; includes /_clock/set_current_utc default 2026-03-01T00:00:00Z).
Errors: 22. Calculations: 4 (lien_amount, surplus_distribution waterfall, sale_charges pinned-rounding, high_bid_selection) — 3 carry variants.
State machines: 7 — StorageUnit, LienNotice, Auction (branches at close), Bid, Sale (parallel payment_status × cleanout_status), Settlement, Dispute (cyclic UNDER_REVIEW ↔ NEEDS_INFO).
Concurrency: 1 OCC rule (bid-supersede stale auction version, 412). Roles: 4 — PlatformAdmin (opaque), FacilityOperator/Buyer/Tenant (entity_backed).
§1.8 depth: 18 instances (9 rules × 2). §1.9 breadth: 38 instances (28 active + 10 excluded_because stubs).
Design note: unit LIEN_MATURED → IN_AUCTION flip moved from auction scheduling to auction open (matured unit can hold multiple SCHEDULED auctions) to make per-unit window-overlap rule reachable.

## Step 3: Copy INSTRUCTION.md — 2026-07-07

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (bash-only).

## Step 4: Generate PRD — 2026-07-07

workspace/PRD.md generated (272 lines, 5 top-level sections, 10 §2 subsections, 8 §3 subsections). 40 endpoints documented (matches scaffold), 22 error codes (matches scaffold). Hard Contracts (field coverage 65 ids/0 missing, rule coverage incl. OCC + validation ordering + 4 calcs, §3 path purity 0 leaks) all PASS. §2.2 byte-identical to canonical. Confirmed: neither design YAML read.

## Step 5: Generate unit tests — 2026-07-07

test_helpers/ (9 files) + test_suite/ (conftest + 8 domain files). 64 test functions total. Queue A (Difficulty): 36 tests, all 18 instances (9 rules × 2) covered ≥2 each. Queue B (Corner): 28 tests, all 28 non-stub instances ≥1 each. 10 excluded_because stubs skipped (as required). No instances skipped for PRD-filter reasons. bid_increments_auction_version translated relationally (version_after == version_at_open+1, PRD §2.7) since PRD §2.4 leaves initial version unpinned. All 83 PRD citations verified verbatim; pytest --collect-only → 64 collected, no import errors.

## Step 6: Generate implementation — 2026-07-07

workspace/implementation/ — app.py, requirements.txt, start.sh. 40 endpoints. In-memory only (10 dicts keyed by UUID + logical clock + seq counter; no disk, no seeding). start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, guarded pip install. Decimal/ROUND_HALF_UP money math; envelope, pagination, logical clock default 2026-03-01T00:00:00Z, OCC on bids, parallel Sale axes, cascades, dispute reversals all implemented. Verified full pipeline boot end-to-end.

## Step 7: Test + fix loop — 2026-07-07

Iterations run: 2 (initial sweep + 1 fix + confirming sweep). Sweep run as 2 waves of 4 (host-saturation guard).

Tests deleted: None.

Fixes applied to test_helpers/:
- test_helpers/fixtures.py — setup_buyer_suspended_with_open_sale: after forfeiting sale_a (requires clock past its payment deadline, which suspends the buyer), reset the clock to CLOCK_WITHIN_PAYMENT_WINDOW before returning. Why: sale_a and sale_b are created at the same auction close, so they share the identical 2026-03-24 payment_deadline. Leaving the clock past that deadline confounded the pay-on-sale_b attempt — both the expired-window guard and the suspension guard tripped.
- test_helpers/constants.py — added CLOCK_WITHIN_PAYMENT_WINDOW = "2026-03-23T00:00:00Z", a waypoint strictly inside the still-open payment window.

Fixes applied to implementation/: None. Implementation was correct.

Root cause: single consistent failure (test_suspended_buyer_cannot_pay_second_sale, all 8 rounds) expected ERR_BUYER_SUSPENDED but got ERR_PAYMENT_WINDOW_EXPIRED. PRD §3.6 lists payment guards in order — UNPAID, then payment-window check (ERR_PAYMENT_WINDOW_EXPIRED), then not-SUSPENDED check (ERR_BUYER_SUSPENDED); impl faithfully checks window before suspension. Fixture confound (both conditions violated at once) made it look like a precedence bug; under PRD order the window error correctly wins. Fix isolates suspension in the fixture rather than weakening a PRD-required check.

Final confirmation: all 8 rounds passed 64/64 (total test count: 64).

## Step 8: Finalize PRD — 2026-07-07

PRD_FINALIZED.md created, byte-identical to PRD.md (272 lines, 0-line/0% delta). Zero substantive edits. Sole Step 7 fix was a pure fixture-bug repair (test_helpers/ clock reset) that touched no implementation logic and revealed no PRD ambiguity — payment-guard precedence (UNPAID → ERR_PAYMENT_WINDOW_EXPIRED → ERR_BUYER_SUSPENDED) already stated in PRD §3.6 and matched by app.py:853-859.

## Step 9: Complete PRD — 2026-07-07

PRD_COMPLETED.md created from PRD_FINALIZED.md. 272 lines / 38,287 chars → 272 lines / 39,690 chars (+1,403 chars; no line delta, all in-paragraph inserts/revisions). 7 changes: 5 ambiguity-pins, 2 mismatch-revisions.
- §2.3 Pagination — insert — created_at ties break by insertion order (app.py:216-217).
- §2.3 Pagination — insert — documented optional exact-match filter query params on /units,/bids,/sales,/disputes (app.py:403-412,751-760,838-844,1039-1048).
- §3.4 Bidding — insert — high-bid third-level tiebreak: equal amount+placed_at → insertion order (app.py:270-275).
- §3.4 retract — insert — mismatch — retraction refreshes updated_at only if it changes standing high bid; never increments version (app.py:775-781).
- §3.5 no-sale close — insert — resets high_bid_cents=0, high_bid_id=null (app.py:650-653,278-285).
- §3.8 dispute create — insert — raised_by must agree with acting role else ERR_FORBIDDEN (app.py:1002-1003).
- §3.8 dispute resolve — insert — decision input tokens UPHOLD/DENY (app.py:1098-1099).
- §4 endpoint table — revise — mismatch — /sales/{id}/settlement returns paginated array envelope, empty until settled (app.py:966-971).
Unchanged (already pinned): lien/waterfall/tax formulas + rounding, state transitions/cascades, §2.10 validation ordering, deposit hold/forfeit, onsite 120-min spacing, half-open window overlap, OCC/ERR_STALE_VERSION.

## Pipeline complete — 2026-07-07

All 9 steps finished. Final: 64 tests, all 8 stability rounds 64/64. Artifacts: SCAFFOLD.yaml (+DIFFICULTY/CORNER designs), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/, test_suite/, workspace/implementation/ (in-memory Flask, start.sh). results.{1..8}.json all passing.
