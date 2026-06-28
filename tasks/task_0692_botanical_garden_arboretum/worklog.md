# Worklog — task_0692_botanical_garden_arboretum

## Step 1: Create Task Directory — 2026-06-28T09:25:48.000Z

Directory provided verbatim by execution directives (skipped directory-scan to avoid parallel-run ID collisions). `tasks/task_0692_botanical_garden_arboretum/` and `workspace/` already existed on disk. Using as {task_dir} for all 9 steps.

## Step 2: Generate Scaffold — 2026-06-28T09:44:01.000Z

All three files are valid and complete. Here is the final summary.

## Summary

Generated all three scaffold artifacts for **task_0692_botanical_garden_arboretum** (Expert difficulty), passing `scaffold_lint.py` clean and verified for grounds-resolvability, enum closure, role coverage, and forbidden-vocabulary.

**Files written** (`/home/ubuntu/github/CodingPRD/tasks/task_0692_botanical_garden_arboretum/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Design profile**: primary archetype quota/allocation (timed-entry slot capacity), secondary pricing-engine; layers = rate/threshold triggers, cascading side effects, dual-variant calculation, optimistic concurrency. **Flat topology** under `api_prefix: /v1` (FK in body) — chosen deliberately for diversity and to satisfy the lint's collection-segment inference.

**Scaffold contents (§1.1–§1.7):**
- **Entities: 12** — Garden, MembershipPlan, Membership, TimeSlot, Reservation, EventTicket, ProgramSession, Registration, Venue, Rental, Donation, ConservancyFund (20 FKs, all with reverse-reachability GETs).
- **State machines: 8** — Membership (cyclic ACTIVE→ACTIVE renew + recoverable LAPSED), Reservation (fork-join HELD→{CHECKED_IN,EXPIRED,CANCELLED}), Registration (compound waitlist/promotion), Rental (branching confirm/reject), ConservancyFund, ProgramSession, EventTicket, Donation. **1 concurrency rule** (OCC on Membership.version for reservation create).
- **Calculations: 9** — join_fee_proration, renewal_credit (dual-variant vs join), reservation_admission (branch on reciprocal), event_ticket_pricing (round-per-ticket-then-sum), rental_pricing (subtotal-keyed discount, quoted vs final), donation_deductible + conservancy_match (dual-variant, different domain), program_tuition, guest_pass_grant.
- **Validations: 15** (priority-ordered, categories auth→existence→referential→state→constraint→temporal→safety→fiscal).
- **Endpoints: 51** (28 POST / 23 GET; the GET count is mostly mandatory FK reverse-reachability infrastructure) including `POST /_clock/set_current_utc` with default `2026-04-01T00:00:00Z`.
- **Error catalog: 23**.
- **Roles: 5** — GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer (opaque), Visitor (entity_backed:Membership); peer_roles model.

**Design instance counts:**
- **§1.8: 19 instances** across all 9 difficulty rules (2 each, with combinatorial_formula carrying 3 to cover modes a/b/c). All formula-derived asserts pre-computed as literals (e.g. renewal 23014, event-ticket 3837 vs sum-then-round 3838, rental 102000 vs 120000, conservancy match capped at 10000).
- **§1.9: 45 instances** (41 active + 4 `excluded_because` stubs that each cite a real §1.8 instance) spanning all 9 claim-extraction-guide sections.

**Lint verdict**: `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (267 calls scanned).

## Step 3: Copy Shared Files — 2026-06-28T09:44:05.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0692_botanical_garden_arboretum/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T09:49:35.000Z

Generated `workspace/PRD.md` (254 lines) from the botanical-garden/arboretum scaffold.

**Sections covered:** §1 Introduction (allocation-vs-pricing framing), §2 Global Specifications (RBAC 5 roles, §2.2 response envelope, pagination, common props + logical clock startup 2026-04-01T00:00:00Z, time-driven sweeps & cascades, money/rounding half-up, tenant isolation + left-to-right reference validation, OCC on Membership.version, full 16-check validation priority ordering), §3 Business Logic (catalog, membership lifecycle dual-variant join-vs-renewal pricing, timed-entry reservations, event tickets, program registration + waitlist promotion, venue rentals provisional vs final pricing, donations/conservancy match), §4 Endpoint table (all 52 endpoints, 4 cols), §5 Error catalogue (23 error IDs, 2 cols).

**Hard Contracts:** Field coverage PASS (61/61 entity fields, 5 special request-body fields, 3 clock outputs, all query_params). Rule coverage PASS (16-rule validation ordering, OCC, all state-machine transitions, 9 calculations, sibling-branch symmetry). Path-purity PASS (0 path tokens in §3). §2.2 byte-identical to canonical source.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate Unit Tests — 2026-06-28T10:04:38.000Z (launched concurrently with Step 6)

Generated complete test infrastructure for `task_0692_botanical_garden_arboretum` (Expert tier).

**`test_helpers/` (Stage 1) — 9 files:** types.py (entity TypedDicts + status/role enums; all carry `version`), api_client.py (one method per endpoint incl. `/_clock/set_current_utc`), api_errors.py (24 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (4 opaque operator roles + `make_visitor_headers` for entity-backed Visitor/Membership), fixtures.py, `__init__.py`. Imports verified clean against installed `prd_bench_local_runner.testing`.

**`test_suite/` (Stage 2) — 7 test files + conftest:** 79 test functions, all collecting cleanly.

**Coverage (design-index-only):** Queue A (Difficulty) 19/19 instances × 2 tests = 38. Queue B (Corner) 41/41 non-stub instances ≥1 test = 41. 4 `excluded_because` stubs correctly NOT translated; all 4 difficulty_instance cross-refs resolve. **No instances skipped** — all passed the PRD-first two-condition filter.

**Audits passed:** every docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag (all 79 resolve to real instances); all 108 quoted PRD citations verified verbatim/rule-bearing/full-sentence; py_compile clean; 79 tests collect with no import errors.

## Step 6: Generate Implementation — 2026-06-28T10:04:38.000Z (launched concurrently with Step 5)

Built Python + Flask REST API at `workspace/implementation/` (24 source files).

**Files:** start.sh (foreground launcher; guards pip install on cheap `import flask` check, then `exec python3 app.py`), requirements.txt (Flask==3.0.3), app.py (12 blueprints, error handlers, binds 0.0.0.0:$PORT default 10000, threaded=False), db.py (in-memory Store + logical clock @ 2026-04-01T00:00:00Z), errors.py (23 error IDs), response.py (envelope, req_ IDs, ISO-8601-UTC-ms, pagination), middleware.py (X-User-ID/X-User-Role extraction, 5-role validation), services/ (common, calc with Decimal/ROUND_HALF_UP, cascade, serialize), routes/ (11 resource blueprints + clock).

**Endpoints:** 51 routes = clock + 50 `/v1` endpoints. **Storage:** in-memory dicts only, no SQLite/JSON/tmp; empty on every boot, nothing seeded.

**PRD-fidelity note flagged by impl:** §2.7 requires reservation `membership_id` same-garden, but §3.3 allows a reciprocal reservation to attach a different-garden membership in the same network. Since §2.9 orders ERR_CROSS_GARDEN_REFERENCE (prio 5) before ERR_RECIPROCAL_NOT_ELIGIBLE (prio 12), impl exempts the membership FK from same-garden check when `reciprocal=true` (time-slot FK always same-garden). [Flag for Step 7/8 attention.]

## Step 7: Run Tests and Iterate — 2026-06-28T10:19:07.000Z

**Iterations run:** 2 sweeps after diagnosis (1 fix-iteration). Baseline showed 13 unique failing tests across 8 rounds (mix of consistent 8/8 failures and flaky 1–6/8 setup failures); after fixes, two consecutive 8-round sweeps passed 79/79.

**Tests deleted:** None. Every failing test traced to a PRD rule (STEP 1a/1b both held); all failures resolved as either a PRD-faithful implementation bug or a test-artifact mistranslation.

**Fixes applied to `test_suite/`:**
- `test_01_pricing_calculations.py` — `test_rental_quoted_with_discount_final_without_after_lapse` and `test_rental_final_exceeds_quoted_by_exact_discount`: added `expected_status=201` to the `validate_success(api.create_rental(...))` calls. PRD §4 says "Creating a new resource returns HTTP 201"; the tests were asserting the default 200 against a creation. (Test mistranslation; the sibling reservation test already used `expected_status=201`.)
- `test_02_membership_lifecycle.py` — `test_reinstate_lapsed_membership_fresh_term_full_fee`: corrected the expected `term_end` from `2028-04-01` to `2028-03-31`. PRD §3.2 says reinstatement sets "`term_end` to 365 days after now"; reinstating at 2027-04-01 plus 365 days lands on 2028-03-31 because the span crosses the 2028 leap day. The implementation (`timedelta(days=365)`) was already PRD-faithful; the test had assumed calendar +1 year.

**Fixes applied to `implementation/`:**
- `services/common.py` — `check_owner()`: made the Visitor ownership gate a no-op when `owning_membership_id` is empty. PRD §2.1 scopes ownership to "a mutation on a **member-owned resource**" and states "Ownership checks on any resource that references a `Membership` compare the resource's `membership_id` to `X-User-ID`." A non-member reservation/registration/rental (empty `membership_id`) references no Membership, so no check applies. This fixed 5 consistent 8/8 failures (`test_held_reservation_cancel_releases_held_count`, `test_checkin_cancelled_reservation_on_full_slot_returns_invalid_state`, `test_checkin_cancelled_reservation_returns_invalid_state_isolated`, `test_withdraw_enrolled_promotes_head_waitlister`, `test_withdraw_waitlister_does_not_promote_lower_waitlister`) that were getting ERR_NOT_RESOURCE_OWNER when a Visitor acted on a membership-less resource. The membership-self ownership checks in `memberships.py` (which pass `m["id"]`, never empty) remain strict.
- `app.py` — changed `app.run(..., threaded=False)` to `threaded=True`. This addressed the flaky "API server could not be restarted" setup failures (1–6/8 rounds, hitting different tests each round) caused by the single-threaded dev server serializing the runner's readiness/liveness probe against test requests under 8-way concurrent boot. No PRD-observable behavior change.

**Note on the flagged §2.7/§3.3 reciprocal-membership item:** Examined per the protocol. The implementation's same-garden-FK exemption for reciprocal reservations and the reciprocal pricing/eligibility tests are mutually consistent with PRD §3.3 and the §2.9 error ordering; no test touching this failed and no change was warranted.

**Final sweep confirmation:** Orchestrator re-ran the full 8-round parallel sweep independently (subagent's results files had been cleaned). All 8 rounds `passed == total == 79`, `failed == 0`, `errors == 0`. results.{1..8}.json retained on disk.

**Step 8 gating:** Step 7 made 2 implementation/ fixes + 2 test_suite/ fixes (0 deletions). Non-zero fixes → Step 8 RUNS (not skipped).

## Step 8: Finalize PRD — 2026-06-28T10:21:53.000Z

Produced `workspace/PRD_FINALIZED.md` — a minimal patch of PRD.md. **Line counts:** PRD.md = 254, PRD_FINALIZED.md = 254 (1 line revised in place, ~0.4% touched).

**Changes (1):**
- §2.1 (RBAC / ownership) — *insert* — Added a clause pinning that the Visitor ownership comparison applies only to resources that actually reference a `Membership`; a reservation/registration/rental with an empty `membership_id` is not member-owned, so the ownership check is skipped and a role-permitted Visitor may mutate it regardless of `X-User-ID`. — `services/common.py:192-193` (`check_owner` no-ops on empty `owning_membership_id`).

**Pre-edit search log (Edit 1):** Subject = ERR_NOT_RESOURCE_OWNER gate when Visitor mutates a resource with empty owning membership_id. Impl paths enumerated: common.py check_owner() (no-op for empty owning id else strict compare); reservations.py:195 / registrations.py:127 / rentals.py:167 cancel/withdraw pass rec["membership_id"] (can be empty); memberships.py:107,139,170,210 always pass m["id"] (strict, never skipped); create-paths default membership_id="". Wording scoped to "reservation, registration, or rental" so membership-self ownership stays strict, and preserves the role-permission gate.

**Items examined → NO edit:** test_01 201-vs-200 (PRD §4 already pins "Creating a new resource returns HTTP 201"); test_02 leap-day term_end (PRD §3.2 already pins "365 days after now"); app.py threaded=True (pure test-infra); §2.7/§3.3 reciprocal (impl/tests already mutually consistent).

## Step 9: Complete PRD — 2026-06-28T10:27:26.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` via full impl scan. **File metrics:** source 254 lines / 46,388 chars → completed 254 lines / 48,506 chars (char delta +2,118; all 10 changes are in-paragraph revisions, no new sections/lines).

**Change counts:** ambiguity-pins 7, mismatch-revisions 3.

**Per-change log:**
- §2.1 RBAC — revise — mismatch — added "activating" to the enumerated Visitor ownership-checked mutations — routes/memberships.py:107
- §2.4 Logical clock — insert — ambiguity — clock set to exactly the supplied instant, no forward-only restriction (earlier instants accepted) — routes/clock.py:41
- §2.5 Lapse cascade — insert — ambiguity — "future" registration means session.starts_at >= now — services/cascade.py:142
- §2.8 OCC — revise — mismatch — version bumps on every create-reservation with non-empty membership_id (incl. paid-heads-only); cancel bumps only when guest_heads>0 — routes/reservations.py:126,130 / 205
- §3.1 Program session close — revise — mismatch+ambiguity — both GardenStaff and GardenAdmin may close; closing non-OPEN session → ERR_INVALID_STATE — routes/program_sessions.py:71,73
- §3.2 Membership creation — insert — ambiguity — unset term_start/term_end serialize as JSON null — services/serialize.py:58-59, db.py:50-51
- §3.3 Reservation head-split — insert — ambiguity — pinned ordering of ERR_INVALID_HEAD_SPLIT and expected_membership_version presence/type ERR_VALIDATION relative to version/active-gate checks — routes/reservations.py:54-71
- §3.3 Reciprocal reservation — insert — ambiguity — reciprocal reservation's attached membership exempt from §2.7 same-garden check (reaches reciprocal-eligibility gate instead of 422) — routes/reservations.py:49-51,85-96
- §3.3 Reservation check-in — insert — ambiguity — out-of-window check-in on HELD reservation → ERR_INVALID_STATE — routes/reservations.py:176-177
- §3.5 Waitlisted withdrawal — insert — ambiguity — withdrawn waitlisted registration's own waitlist_rank set to 0 — routes/registrations.py:143
- §3.6 Rental confirm overlap — insert — ambiguity — half-open overlap semantics (windows touching at widened buffer boundary do not collide) — routes/rentals.py:137

## PIPELINE COMPLETE — 2026-06-28T10:27:26.000Z

All 9 steps finished. `workspace/PRD_COMPLETED.md` present on disk. Final stability state: 8/8 parallel rounds × 79/79 tests passed (0 failed, 0 errors), results.{1..8}.json retained. Task directory fully populated: SCAFFOLD×3, worklog, PRD/PRD_FINALIZED/PRD_COMPLETED, test_helpers/ (10), test_suite/ (9), workspace/implementation/ (18).
