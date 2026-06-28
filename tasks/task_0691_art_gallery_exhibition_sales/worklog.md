# Worklog — task_0691_art_gallery_exhibition_sales

## Step 1: Create Task Directory — 2026-06-28T09:25:48.000Z

Directory pre-created by harness; Step 1 scan skipped per execution directives. Using `tasks/task_0691_art_gallery_exhibition_sales` verbatim as {task_dir}. workspace/ subdir already present.

## Step 2: Generate Scaffold — 2026-06-28T09:46:16.000Z

Generated all three scaffold artifacts for **task_0691_art_gallery_exhibition_sales** (Expert difficulty), saved to `/home/ubuntu/github/CodingPRD/tasks/task_0691_art_gallery_exhibition_sales/`:

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**`scaffold_lint.py` verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold contents:**
- **Complexity profile**: primary archetype quota_allocation + secondary ledger_reconciliation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, scheduled_actions; flat topology; parallel state-machine shape; peer_roles; immediate consistency.
- **Entities (12)**: Gallery, Artist, Artwork, Exhibition, WallSlot, Sale, PaymentPlan, LeaseAgreement, OpeningEvent, Rsvp, Loan, Payout — all FKs use the canonical `FK -> {Entity}.id` prefix.
- **State machines (11)**: incl. Sale's two parallel dimensions (settlement_status × shipping_status), cyclic Artwork lifecycle, branching Exhibition; plus 2 concurrency rules (OCC on Exhibition.version for wall-slot placement, on Sale.version for payment posting, both 412).
- **Calculations (8)**: sale_money_breakdown, consignment_split (provisional/final variants), installment_schedule, plan_default_check, lease_buyout, loan_coverage_gap, rsvp_seat_allocation, artist_ledger.
- **Validations (14)**, priority-ordered auth → existence → request → state → OCC → cross-entity → safety → temporal → capacity → fiscal.
- **Endpoints (62)** incl. test-driving `POST /_clock/set_current_utc` (default 2026-04-01T00:00:00Z).
- **Error catalog (17)**; every code referenced at least twice.
- **Roles (4)**: GalleryAdmin/Registrar/SalesAssociate (opaque), Artist (entity_backed:Artist).

**Design instance counts:**
- §1.8: 9 rule_ids × 2 = **18 instances** (2 each).
- §1.9: 9 sections, **39 active instances + 4 `excluded_because` stubs** (each citing a real §1.8 instance by name).
- 61 unique instance names across §1.8 ∪ §1.9; all `grounds[]` resolve to declared §1.1–§1.7 elements; all formula-derived asserts pre-computed as literals; no forbidden concurrency vocabulary; enum-value closure holds for all status fields.

## Step 3: Copy Shared Files — 2026-06-28T09:46:16.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-06-28T09:52:30.000Z

Generated `workspace/PRD.md` — **303 lines** — from the Art Gallery & Exhibition Sales scaffold.

**Structure:**
- §1 Introduction — 2 paragraphs
- §2 Global Specs — 11 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Topology/Identity/Common Properties, 2.5 Nested Retrieval ordering, 2.6 Validation Ordering, 2.7 Logical Clock, 2.8 Monetary Precision, 2.9 OCC, 2.10 Consignment Ledger, 2.11 Wall Map & Loan Calendar as booking ledgers
- §3 Business Logic — 10 lifecycle-staged subsections
- §4 Endpoint table (4 columns, all 62 endpoints) and §5 Error table (2 columns, all 17 errors)

Hard Contracts: Field coverage PASS, Rule coverage PASS, Path purity PASS (457 backtick tokens scanned, 0 path-like).

**Notable coverage decisions:**
- Exhibitions use **closed intervals** (shared boundary = conflict) vs loans using **half-open intervals** (abutting = no conflict) — both stated precisely.
- **Provisional vs final consignment split** rendered with equal density: provisional uses undiscounted-gross-derived net; final uses post-discount net and is the only value that hits the ledger.
- `MAX_MISSED_INSTALLMENTS: 2` embedded as business statement; cadence constant unit-converted to 86,400 seconds.
- Sale params scattered across ≥2 subsections; OCC framing in §2.9.
- Did NOT open either withheld design file.

## Step 5: Generate Unit Tests — 2026-06-28T10:06:50.000Z

Generated complete test infrastructure (Stage 1 `test_helpers/` 9 files; Stage 2 `test_suite/` 10 test files + conftest, **75 tests**).

**Coverage (every audit passed):**
- Queue A (Difficulty): **18/18 instances translated**, each with ≥2 tests (36 difficulty tests).
- Queue B (Corner): **39/39 non-stub instances translated** (≥1 test each); **4 `excluded_because` stubs correctly NOT translated**, all 4 stub cross-references resolve to real difficulty instances translated.
- Every test carries exactly one `Design:` tag; all tags resolve to a real instance name.
- All 100 quoted PRD citations survive a verbatim grep of PRD.md; no skip/xfail markers; no scaffold-leakage; all files byte-compile; 75 tests collect under pytest.

**Notable adjudication (one weakened sub-assertion, not a skip):** in `Corner/state_machines/rsvp_waitlisted_when_capacity_full_then_promoted_on_cancel`, the instance's `confirmed_count seats == 8` assertion is not uniquely PRD-derivable — PRD §3.9 defines `confirmed_count` as "the number of RSVPs in `CONFIRMED` status," which excludes `PROMOTED` rows. Kept the test (asserting the uniquely-derivable WAITLISTED→PROMOTED transition outcome) and dropped only that ambiguous numeric sub-assertion. No instances skipped entirely.

## Step 6: Generate Implementation — 2026-06-28T10:06:50.000Z

Generated complete Python + Flask implementation at `workspace/implementation/` (9 files: start.sh, requirements.txt, app.py, services.py, db.py, response.py, errors.py, middleware.py, clock.py).

**Endpoints: 63 implemented** (all from PRD §4 / SCAFFOLD §1.5).

**Key design decisions:**
- In-memory only, zero seeding — store starts empty on every boot; clock defaults to 2026-04-01T00:00:00Z.
- Decimal round-half-up for money; tax on post-discount net; shipping never taxed.
- Dual-variant consignment split — provisional (undiscounted, not accrued) at reserve vs final (post-discount) at settle; ledger figures computed live so payout complete/reverse conserve invariant.
- Validation ordering per PRD §2.6 (auth → forbidden → existence → invalid_request → state → OCC → business rules); coverage-safety beats schedule-overlap on loans; not-found beats invalid-state.
- Creation-time provenance uses non-version-bumping seed (fresh artwork reads version==1, provenance_count==1); later provenance writes bump version.
- Interval semantics: loans half-open `[out, due)` against full loan history; exhibition windows closed-interval (shared boundary conflicts) for same artwork in non-terminal shows.
- OCC: expected_exhibition_version on wall-slot placement; expected_sale_version on payments; each write bumps parent version by 1.
- RSVP: party-size-weighted capacity, direct WAITLISTED creation, created_at-ASC promotion with no skip-ahead on cancel.
- Artist read-scoping: entity-backed X-User-ID restricts list/get to own artist/artworks/sales/payouts.

## Step 7: Run Tests and Iterate — 2026-06-28T10:10:48.000Z

- **Iterations run:** 1 (a single 8-round parallel stability sweep).
- **Result:** All 8 concurrent rounds passed `75/75` with `failed=0`, `errors=0`. No flakiness surfaced across the union of all rounds. (Confirmed independently by orchestrator reading results.1..8.json.)
- **Tests deleted:** None. No test failed in any round, so no PRD-coverage / unique-derivability deletion was triggered.
- **Fixes applied to `test_helpers/`:** None required.
- **Fixes applied to `implementation/`:** None required.

The implementation already satisfies the full 75-test suite under `--isolation per-test-server` with no diagnostic intervention needed. Clean 8-round parallel sweep on first attempt.

## Step 8: Finalize PRD — 2026-06-28T10:10:48.000Z

SKIPPED per skip-condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step 7 sites. PRD_FINALIZED.md not produced; Step 9 starts from PRD.md.

## Step 9: Complete PRD — 2026-06-28T10:15:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (Step 8 skipped, so started from a `cp` of PRD.md).

**Line counts:** PRD.md = 303 lines, PRD_COMPLETED.md = 303 lines (all edits in-paragraph; no lines added/removed).
**Char delta:** 46,344 → 51,774 chars (+5,430).
**Change counts:** 16 paragraphs touched — 9 ambiguity-pins, 7 mismatch-revisions.

Per-change list:
- §2.1 — insert — ambiguity — non-owned single-resource artist read returns `ERR_FORBIDDEN` (exists-first), list reads silently filter; gallery/exhibition/event/wall-slot reads unfiltered
- §2.3 — insert — ambiguity — list sort tie-break is ascending insertion order; unknown query params ignored
- §2.4 — revise — mismatch — `created_at`/`updated_at` are wall-clock 3-digit; business instant fields render with NO fractional digits
- §2.4 — revise — mismatch — derived fields computed live on read; recomputing ledger/counts does NOT bump the carrying resource's version/updated_at
- §2.6 — revise — mismatch — path-parent existence (3) precedes body well-formedness (4), but body-FK existence (4b) checked after body validation
- §3.1 — revise — mismatch — gallery `clock_utc` is not stored per-gallery; always the live shared clock
- §3.2 — insert — ambiguity — first provenance entry uses event text `CONSIGNED`; creation-time → version 1 / provenance_count 1
- §3.2 — insert — ambiguity — missing/non-string `event` → ERR_INVALID_REQUEST; only empty/whitespace → ERR_DUPLICATE_PROVENANCE_EVENT
- §3.2 — insert — ambiguity — fixed provenance event tokens; terminate/convert write no lease entry; each append bumps version
- §3.3 — insert — ambiguity — open precondition violations all → ERR_INVALID_STATE
- §3.3 — insert — ambiguity — close precondition violations → ERR_INVALID_STATE
- §3.5 — revise — mismatch — settle releases ALL PLACED slots for the artwork across any exhibition
- §3.5 — revise — mismatch — void releases ALL PLACED slots for the artwork across any exhibition
- §3.5 — insert — ambiguity — ship: both guards ERR_INVALID_STATE, shipping-status checked before not-VOID
- §3.7 — insert — ambiguity — loan sweep precondition violations → ERR_INVALID_STATE
- §3.8 — insert — ambiguity — convert's generated sale field values; endpoint returns the lease, not the sale
- §3.9 — revise — mismatch — `confirmed_count` counts CONFIRMED+PROMOTED rows (head count)
- §3.9 — insert — ambiguity — party_size>capacity check after deadline/state guard; 1..10 range at well-formedness
- §3.10 — insert — ambiguity — report window filters on sale updated_at, both bounds inclusive; invalid bounds → ERR_INVALID_REQUEST

## Pipeline Complete — 2026-06-28T10:15:00.000Z

All 9 steps complete. `workspace/PRD_COMPLETED.md` present on disk (51,774 bytes). Final test state: 75/75 passing across all 8 parallel stability rounds under `--isolation per-test-server`.
