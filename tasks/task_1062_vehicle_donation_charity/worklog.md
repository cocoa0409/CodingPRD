# Worklog — task_1062_vehicle_donation_charity

## Step 1: Create task directory — 2026-07-18T00:00:00.000Z

Used pre-assigned directory `tasks/task_1062_vehicle_donation_charity` (Step 1 index scan skipped per launch instruction). Created `workspace/`.

## Step 2: Generate scaffold (Expert) — 2026-07-18T01:00:00.000Z

Generated all three Expert-difficulty scaffold artifacts.
- SCAFFOLD.yaml (§1.0–§1.7) — 13 entities, 69 endpoints, 51 errors, 7 roles, 8 state machines, 6 calculations, 3 OCC concurrency rules, 29 ordered validations.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 9 rule_id blocks × 2 instances = 18 instances.
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 60 instances (55 full recipes, 5 excluded_because stubs).
Profile: workflow_orchestration + ledger_reconciliation; flat topology; parallel state shape; segregation_of_duties; layers = OCC, dual-variant calc, cascading side effects, rate/threshold triggers.
Entities: Donor / CharityAffiliate / Donation / Vehicle / TitleRecord / TowVendor / PickupOrder / SalesVenue / AuctionLot / ProceedsLedgerEntry / TaxReceipt / RemittanceBatch / FollowUpTask.
Dual-variant on two domains (1098-C GROSS_PROCEEDS vs FMV_FULL; remittance BATCH_ROUNDING vs PER_LINE_ROUNDING); combinatorial FMV three-factor with salvage cap/floor; proceeds waterfall with tow-allowance cap on post-fee net; cycles on TitleRecord/AuctionLot/RemittanceBatch; parallel status × payout_status on Donation; depth-4 cascade (sale → ACCRUED → charity pledge → auto-batch → task); 3 priority-conflict pairs; boundary probes on $500 receipt threshold; cross-entity gates AuctionLot→TitleRecord, PickupOrder→TowVendor; buffered pairwise tow windows vs calendar-day venue capacity; conserved quantities (charity accrual money, vendor slot count).
Lint verdict: clean — 69 endpoints, 13 entities, 18 §1.8 + 55 §1.9 instances, 780 calls scanned, 0 violations.
Orchestrator verification: all 3 files pass yaml.safe_load; 33 global_constants declared; no undeclared named constants (scan found only enum members).

## Step 3: Copy shared files — 2026-07-18T01:05:00.000Z

Copied INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-18T01:15:00.000Z

PRD generated at workspace/PRD.md (475 lines).
Structure: §1 Introduction → §2 (12 subsections: RBAC, response envelope, pagination, identity/versioning, logical clock, money precision, OCC, 29-step validation ordering, cascades/derived counters, proceeds-ledger principle, follow-up obligations, nested reads) → §3 (10 domain subsections) → §4 endpoint table → §5 error table.
Coverage: 69 endpoints, 51 error codes.
Hard Contract: field coverage PASS (91/91 fields, 51/51 request bodies, 12/12 query params); rule coverage PASS (29/29 validations, 3/3 OCC, 8 machines/48 transitions, 6/6 calculations, 69/69 side-effects, 7/7 sibling-branch symmetry groups); path purity PASS (631 backtick tokens, 0 leaked paths in §3).
Authoring notes: constants embedded with unit conversion; boundary inclusivity explicit (strict > on 50000-cent gross-proceeds threshold, half-open windows, buffer-exactly-apart accepted); two independent Donation axes + four-link accrual cascade stated in §2.9/§2.10 and §3.7. No design YAML opened.
Orchestrator verification: PRD byte-count stable across 45s; all 69 scaffold endpoint paths and all 51 error ids present in PRD.md.

## Step 7: Test and fix loop — 2026-07-18T02:15:00.000Z

All 8 rounds green.

**Iterations run:** 2 sweeps (8 rounds each, 2 waves of 4).
- Sweep 1: 91/92 in all 8 rounds — a single deterministic (non-flaky) failure.
- Sweep 2: 92/92 × 8, 0 failures, 0 errors.

**Tests deleted:** none.

**Fixes applied to test_helpers/:** none. setup_pickup_blocked_donation (fixtures.py:338) was audited and found faithful — it drives a donation to PICKUP_BLOCKED via three real failed tows, exactly as PRD §3.5 describes.

**Fixes applied to implementation/:**
- workspace/implementation/routes/pickups.py, create_pickup_order — the donation-state gate was `status != "ACCEPTED"` → ERR_INVALID_DONATION_STATE, now `status not in ("ACCEPTED", "PICKUP_BLOCKED")`.

**Why:** PRD §3.5 states verbatim "a donation whose `pickup_attempts` has already reached three admits no further reservation, refused with `ERR_PICKUP_ATTEMPTS_EXCEEDED`" (also §2.8 check 24). But §3.5 also says a third failure moves the donation ACCEPTED → PICKUP_BLOCKED — so pickup_attempts == 3 implies PICKUP_BLOCKED always. The impl's ACCEPTED-only gate made an explicitly-stated PRD rule unreachable dead code, masking ERR_PICKUP_ATTEMPTS_EXCEEDED behind ERR_INVALID_DONATION_STATE. The generation-time judgement call ("pickup-order creation requires donation ACCEPTED") was the source of the bug: PRD §2.8 check 9 is scoped to "every transition endpoint," and pickup-order creation is a creation endpoint — PRD states no donation-state precondition for it at all. The fix keeps the narrowest change consistent with PRD rather than dropping the gate entirely.

Orchestrator verification: results.{1..8}.json all show passed=92 total=92 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-07-18T02:25:00.000Z

PRD_FINALIZED.md written. PRD.md 475 lines / 73,353 bytes → PRD_FINALIZED.md 475 lines / 74,173 bytes (0 lines delta, 2 lines revised in place, +820 bytes / +1.1%).

Changes:
- §2.8 check 9 (Source-state legality) — revise — extended the "applies to every transition endpoint" scope note to also cover creation endpoints with a parent-donation disposition gate, naming pickup-order creation as admitting only ACCEPTED or PICKUP_BLOCKED — implementation/routes/pickups.py:36
- §3.5 ¶1 (Getting the Car Into Custody) — revise — added the donation-disposition precondition for reserving a tow window, its ERR_INVALID_DONATION_STATE refusal, its ordering slot, and the note that a blocked donation falls through to the attempt budget — implementation/routes/pickups.py:36,64

Pre-edit search log:
- Edit 1: subject = which endpoints carry a source-state precondition. Enumerated every ERR_INVALID_DONATION_STATE raise site; creation endpoints with donation gates: pickups.py:36, titles.py:83 (+SUBMITTABLE_DONATION_STATES titles.py:17), lots.py:48, receipts.py:28; transition sites confirmed unaffected (donations.py:134,154,171,201,217; pickups.py:123,155; lots.py:114,161,181,210; receipts.py:93,148). Adjustment: original draft "and to pickup-order creation" implied exclusivity — falsely excluding title/lot/receipt creation gates; reworded to non-exclusive "and also to those creation endpoints whose parent donation must sit in a declared disposition — among them pickup-order creation, …".
- Edit 2: subject = donation-state precondition on tow-window reservation and its precedence. Enumerated pickups.py:20-84 (check order: version 32 → donation status 36 → vendor ACTIVE 40 → window coherence 42 → not-past 46 → separation 50-60 → capacity 62 → attempt budget 64), pickups.py:113-201 (complete/fail require donation exactly ACCEPTED; cancel has no donation gate), donations.py:201-223 (drop-off requires ACCEPTED + pickup_required false; reset requires PICKUP_BLOCKED, zeroes pickup_attempts and returns to ACCEPTED); cross-checked §2.8 items 8/13/20/21/22/23/24 for ordering. Adjustments: scoped the new sentence strictly to reservation so it doesn't leak onto completion/failure (already pinned to ACCEPTED); replaced a draft clause "unless a pickup reset has intervened" (false — reset zeroes attempts AND returns status to ACCEPTED, so PICKUP_BLOCKED always implies attempts >= 3) with "is then refused by the attempt budget below rather than by this one".

## Step 9: Complete PRD — 2026-07-18T02:35:00.000Z

PRD_COMPLETED.md written. PRD_FINALIZED.md 475 lines / 74,173 chars → PRD_COMPLETED.md 475 lines / 78,145 chars (+3,972 chars, 15 lines touched, no lines added/removed — all edits in-paragraph).
Counts: 15 ambiguity-pins, 0 mismatch-revisions. The finalized PRD had no passage contradicting implementation/; every gap was silence.

Changes:
- §2.8 (item 9) — insert — ambiguity — URL-path entity judged before parent donation (lot/title/pickup before donation) — routes/lots.py:112-115, routes/titles.py:80-87, routes/pickups.py:120-126
- §2.8 (item 6) — insert — ambiguity — multi-FK payloads resolve in narrative order (donor_id before charity_id; donation_id before tow_vendor_id/venue_id) — routes/donations.py:61-62, routes/pickups.py:29-30, routes/lots.py:45-46
- §3.1 — insert — ambiguity — suspend accepted from any status incl. already-SUSPENDED, bumps version again — routes/reference.py:69-74
- §3.2 — insert — ambiguity — recording an exception has no state precondition, may reset to NONE — routes/donations.py:254-262
- §3.2 — insert — ambiguity — donation-listing ownership guard bites only on the caller's matching filter; omitted filter yields unfiltered listing — routes/donations.py:105-110
- §3.3 — insert — ambiguity — empty condition_grade takes condition multiplier of one — services/calc.py:37
- §3.3 — insert — ambiguity — all four inspection fields optional (omitted keeps stored value); odometer_miles >= 0 — routes/vehicles.py:104-107
- §3.5 — insert — ambiguity — creating a pickup order advances donation.version though no donation field changes — routes/pickups.py:83
- §3.5 — insert — ambiguity — actual_tow_cost_cents required integer >= 0; zero legitimate — routes/pickups.py:118
- §3.7 — insert — ambiguity — zero net suppresses the entire cascade (no ledger entries, no balance change, no sweep) while money fields and SOLD disposition still written — routes/lots.py:139-147
- §3.8 — insert — ambiguity — control_number format "CN-" + six zero-padded digits from one server-wide never-reused counter — db.py:101-103, routes/receipts.py:102
- §3.9 — insert — ambiguity — REMITTANCE_SETTLEMENT is a DEBIT of net_to_charity_cents; CHARITY_FEE_DEBIT also DEBIT; provisional_fee_cents not recomputed at close — routes/batches.py:115-131
- §3.9 — insert — ambiguity — reopen leaves dispute_reason standing and provisional_fee_cents stale until next individual read — routes/batches.py:219-227
- §3.9 — insert — ambiguity — OPEN-batch refresh is a read (no updated_at/version bump), fires only on individual GET never on listing — routes/batches.py:50-51, services/domain.py:236-243
- §3.10 — insert — ambiguity — charity_id required on charity-summary report; absence is ERR_INVALID_REQUEST, tested after the ownership guard and before the affiliate resolves — routes/ops.py:80-87

Triage of flagged judgement calls: batch-create gross_cents == 0 with live provisional_fee_cents was already pinned by the finalized PRD (§3.9 + §4 endpoint row) — only extended to the listing path and version-bump question. Settlement direction/amount, actual_tow_cost_cents >= 0, and §2.8 unconditional check ordering were genuine silences, now pinned.

## Pipeline complete — 2026-07-18T02:40:00.000Z

Steps 1–9 complete. Final state: 92/92 tests passing across all 8 sweep rounds; SCAFFOLD + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (92 tests), workspace/implementation/ (69 routes).
