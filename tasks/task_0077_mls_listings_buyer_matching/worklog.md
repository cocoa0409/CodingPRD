# Worklog — task_0077_mls_listings_buyer_matching

## Step 1: Create task directory — 2026-06-01T00:00:00.000Z

Created `tasks/task_0077_mls_listings_buyer_matching/` and `workspace/` subdirectory. Scenario: MLS Listings & Buyer Matching (dual agents Listing/Buyer, showing appointments, Lockbox, Offer/Counter/Multiple Offer, Contingency Inspection/Appraisal/Financing, Co-op commission). Difficulty: Expert (Step 2 only).

## Step 2: Generate scaffold — 2026-06-01T01:06:00.000Z

Generated all three scaffold artifacts at **Expert** difficulty band. `scaffold_lint.py` returns VERDICT: clean lint (435 calls scanned across §1.8+§1.9, all conform to §1.5; all FKs reverse-reachable).

Files written:
- `SCAFFOLD.yaml` — §1.0–§1.7 + concurrency_rules (1211 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design` (9 rules × 2 = 18 instances, 1301 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design` (34 instances incl. 3 `excluded_because` stubs, 1425 lines)

Structure:
- 10 entities: Brokerage, Agent, Buyer, Listing, Lockbox, ShowingAppointment, Offer, CounterRound (append-only event log), Contingency, CommissionLedger.
- 46 endpoints, 20 error codes, 2 OCC concurrency rules (both on `Listing.version`: offer-accept stale, listing-close stale).
- 5 state machines: Listing (DRAFT→ACTIVE→UNDER_CONTRACT↔ACTIVE→PENDING→CLOSED + WITHDRAWN; compound/posture-driven), Offer (cyclic SELLER_COUNTERED↔BUYER_COUNTERED loop + accept/reject/withdraw), Contingency (PENDING→{SATISFIED,WAIVED,FAILED} divergent compensation), Lockbox, ShowingAppointment.
- 6 calculations: offer_negotiation_state (projection), listing_offer_posture (aggregation→SINGLE/MULTIPLE/NONE), net_to_seller (dual-variant provisional vs final), run_commission_split (waterfall pinned nested-rounding order), financing_dti (threshold 0.43), showing_overlap (buffered half-open interval_merge).

Expert-band choices: primary archetype multi-party-negotiation blended with temporal-windowing; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Cyclic state-machine, peer_roles RBAC (dual-agency on same listing forbidden), hybrid topology cross-aggregate FKs. 3-hop transitive cascade (accept→UNDER_CONTRACT→auto-PENDING when no contingencies); FAILED-contingency compensation invariant; pinned nested-rounding divergence at sale 16666675; DTI boundary 0.43; half-open showing buffer adjacency boundary.

## Step 3: Copy INSTRUCTION.md — 2026-06-01T01:06:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-01T01:12:00.000Z

Generated `workspace/PRD.md` — 6,147-word / 272-line prose PRD for MLS Listings & Buyer Matching API.

Sections: §1 Introduction (dual-agent segregation, non-linear lifecycle, OCC motivation); §2 Global Specs (10 subsections — RBAC all 3 roles + both identity translations, pagination, common properties with `common_fields:false` callout for Buyer/CounterRound, hierarchical 404, OCC on accept+close keyed on expected_listing_version/ERR_STALE_VERSION 412, monetary precision + pinned commission rounding order, brokerage defaults, showing windows, turn/segregation); §3 Business Logic (9 lifecycle subsections); §4 endpoint table (47 endpoints); §5 error table (20 error IDs).

Hard Contracts all PASS: Contract 1 field-name coverage 52/52; Contract 2 rule coverage (both OCC, all calcs incl. DTI 0.43 + 0.005 factor, commission nested-rounding, net-to-seller dual variant, showing half-open buffer, offer-state projection, posture aggregation, all transitions/cascades/validations/errors); Contract 3 §3 path purity 369 tokens, 0 violations. Neither design YAML opened.

## Step 5: Generate unit tests — 2026-06-01T01:32:00.000Z

Generated test infrastructure. test_helpers/ (Stage 1) — 9 files: types.py (entity TypedDicts, Buyer/CounterRound omit updated_at/version), api_client.py, api_errors.py (20 error IDs + HTTP map), assertions.py, factories.py, constants.py (MAX_DTI, MONTHLY_PAYMENT_FACTOR, commission defaults), test_users.py (entity-backed agent header builders), fixtures.py (composite chains), __init__.py.

test_suite/ (Stage 2) — 7 test files + conftest.py, **68 tests total**, all collecting cleanly.
- Queue A (Difficulty): 36 tests covering all 18 instances (9 rules × 2), each ≥2 tests.
- Queue B (Corner): 32 tests covering all 31 non-stub instances, each ≥1 test.
- Skipped: 3 `excluded_because` stubs (correctly NOT translated — cross-ref to real difficulty instances: stale_version_on_accept_412, dual_agency_forbidden_422, net_sheet_provisional_vs_final_reconcile). No instances skipped for PRD-coverage failure.

## Step 6: Generate implementation — 2026-06-01T01:32:00.000Z

Built Python + Flask implementation at `workspace/implementation/`. Self-reported **68/68 tests pass** under per-test-server isolation.

13 files (12 Python modules + start.sh): app.py, db.py (in-memory + logical clock), errors.py, response.py, middleware.py (auth/RBAC), helpers.py, serializers.py; routes/ (setup, listings, lockboxes, showings, offers, contingencies); services/ (negotiation counter-replay, money commission/net-sheet/DTI with Decimal, state cascades/compensation, entities). All 47 endpoints. In-memory dicts keyed by UUID, no seeding. Decimal ROUND_HALF_UP, pinned nested rounding (round total then co-op off rounded total, listing side absorbs penny), DTI exact Decimal at 0.43. Cascades for accept/contingency satisfy-waive/fail-compensation. Buyer & CounterRound append-only.

NOTE from impl subagent: correct runner invocation is `--start-command "cd <abs_impl_dir> && bash start.sh"` (regex expects `cd <dir> && <cmd>`); bare path makes restarts run from pytest rootdir and fail.

## Step 7: Run tests and iterate — 2026-06-01T01:50:00.000Z

Iterations run: 2 (initial diagnostic sweep + verification sweep). Final 8-round parallel sweep fully green — **68/68 in all 8 rounds, union failure count = 0**.

Root cause: NOT a test or implementation logic bug. Every test failed in *some* round (union = all 68) while each round still passed 63–65/68 — signature of a flaky server-boot problem, not assertion failures. Error on every failure: `API server ... could not be restarted before <test>`. Cause: `start.sh` ran `pip install -q -r requirements.txt` on every boot; under per-test-server isolation (68 restarts) × 8 concurrent rounds = ~544 contended pip invocations, too slow to boot inside the runner's restart window, so a random subset timed out each round.

Tests deleted: none (no PRD-coverage or derivability issue — failures were pure infrastructure flakiness).
Fixes applied to `test_helpers/`: none.
Fixes applied to `test_suite/`: none.
Fixes applied to `implementation/`: `start.sh` only — guarded the dependency install (`pip install` now runs only when `python3 -c "import flask"` fails, instead of on every restart). Non-behavioral launcher/boot-reliability fix; no PRD-relevant behavioral change.

## Step 8: Finalize PRD — SKIPPED — 2026-06-01T01:50:00.000Z

Skip rationale: Step 7 produced 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 *behavioral* `implementation/` fixes. The sole change was to `start.sh` (dependency-install guarding) — a launcher/boot-reliability fix that reveals no PRD silence or PRD/impl mismatch and pins no behavioral choice. There is no Step-7-fix site for Step 8 to align PRD prose to. `PRD_FINALIZED.md` not produced; Step 9 starts from `PRD.md` and performs the full comprehensive PRD-vs-implementation scan regardless.

## Step 9: Complete PRD — 2026-06-01T01:58:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation/ scan (started from PRD.md, Step 8 skipped). PRD.md 272 lines / 42,540 chars → PRD_COMPLETED.md 272 lines / 44,241 chars (char-delta +1,701; all edits in-paragraph, no new sections). 9 changes: 7 ambiguity-pins, 2 mismatch-revisions.

- §2.4 Versioning — insert — ambiguity — `version` initial value = 1 on creation (entities.py:11)
- §3.3 Lockboxes — insert — ambiguity — disable non-INSTALLED lockbox → ERR_INVALID_STATE 409 (lockboxes.py:63)
- §3.4 Showings confirm — insert — ambiguity — confirm requires REQUESTED, checked before lockbox-disabled check (showings.py:116)
- §3.4 Showings cancel/complete/no-show — insert — ambiguity — state gates, complete/no-show state-check before clock gate (showings.py:148,172)
- §3.5 Submit offers — insert — mismatch — target listing must be ACTIVE else ERR_INVALID_STATE 409, ordered after dual-agency before suspension (offers.py:48)
- §3.7 Financing gate — insert — ambiguity — monthly_income_cents==0 → DTI fails (no div-by-zero) (money.py:41)
- §3.8 Commission ledger — insert — ambiguity — lookup is paginated list/array envelope (listings.py:208)
- §3.9 Net-sheet — revise — mismatch — provisional basis uses accepted offer's price when UNDER_CONTRACT, else leading live offer (listings.py:184)
- §3.9 Net-sheet — insert — ambiguity — no live+no accepted offer → all three computed fields null, listing_id echoed (listings.py:168)
- §3.6 Reject offer — insert — ambiguity — wrong-side role → ERR_FORBIDDEN_ROLE 403; non-live status → ERR_INVALID_STATE 409 (offers.py:247)

## Pipeline complete

Final 8-round stability sweep verified: results.{1..8}.json all 68/68. Task fully green. Deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (68 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}.
