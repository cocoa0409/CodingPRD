# Worklog — task_1467_out_home_billboard_inventory_booking

## Step 1: Create Task Directory — 2026-08-13T09:51:00.000Z

Task directory `tasks/task_1467_out_home_billboard_inventory_booking/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (Step 1 treated as DONE per invocation instructions). No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T11:20:00.000Z

All three scaffold artifacts are generated and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_1467_out_home_billboard_inventory_booking/`.

**Verbatim summary:**

- **Entity count: 10** — RateCard, Face, Permit (self-referential renewal chain), MaintenanceWorkOrder, AdvertiserAccount, Campaign, Flight, ArtworkOrder, PostingRecord, MakeGood (flat topology, all `common_fields: true`)
- **State machines: 10** — one per entity; non-linear shapes include ArtworkOrder revision cycle (SUBMITTED→IN_PRODUCTION→REVISION_REQUESTED→SUBMITTED), Campaign parallel dimensions (status × billing_status), Flight cycle (MISSED→LIVE) plus 5 clock-swept auto-transitions, Face cyclic posture machine, WorkOrder reopen cycle, Permit renewal/expiry/reinstate cycle
- **Calculations: 7** — flight_gross_cost (tiered/conditional, mode a + holdover variant), campaign_volume_discount (pinned round-per-flight-then-sum, mode b), estimated_impressions (forward_looking), delivered_impressions (chronological replay with AUDIENCE_MEASURED precedence), make_good_credit (4 reason branches), loop_slot_capacity (aggregate), face_availability_calendar (dual-variant interval_merge)
- **Validations: 14** (priority-ordered; deliberate conflict pairs: business_safety-vs-business_constraint at P7/P10, state-vs-business_fiscal at P5/P14)
- **Endpoints: 41** (includes `POST /api/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`); note this exceeds the Expert guideline band of 20–32 because the FK reverse-reachability hard constraint (lint check f) over 12 FK edges plus the scenario's nine sub-domains require it — difficulty is concentrated in interaction density per §0.4 rather than CRUD volume
- **Error count: 32** (10 resource-specific 404s, auth/400s, state 409s, business 409s, segregation 403, credit 402, OCC 412)
- **§1.8 instances: 18** (exactly 2 per each of the 9 difficulty rules, all with structured `setup_api_calls` chains, placeholder closure, and formula-derived literal asserts — e.g., discount per-flight-sum 6401370 vs sum-then-round 6401371; missed-posting credit 123214; illumination-outage credit 18482; holdover 2 weeks 632500)
- **§1.9 instances: 55** (45 full test recipes + 10 `excluded_because` stubs; sections: entities 7, state_machines 9, calculations 7, validations 10, endpoints 2, errors 9, rbac 4, cross_cutting_layers 6, consistency_model 1)
- **Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (826 calls scanned, 0 violations)

**Notable design decisions:**
- 3 OCC concurrency rules, all passing §1.2.1's serial-observability filter: `flight-create-stale-face` (quote priced on superseded face data), `flight-confirm-stale-campaign` (discount tier locked from superseded contracted total), `rate-card-update-stale`
- Depth-4 transitive cascade from the clock-set trigger (Permit EXPIRED → Face PERMIT_SUSPENDED → Flight.suspension_started_at → Campaign.delivery_posture) and a depth-3 cascade from posting verification (PostingRecord VERIFIED → Flight LIVE → Campaign auto-ACTIVE), satisfying Rule 4 from different triggers
- Two interval semantics for Rule 8: static-face closed date intervals with a mandatory 1-day changeover gap vs maintenance half-open datetime windows (with an explicit ILLUMINATION_OUTAGE exemption so reactive outages can overlap LIVE flights — added during §1.9's §1.5 audit pass)
- Segregation-of-duties role model (9 opaque roles): installer ≠ verifier on photo proof; user-proposer ≠ approver on make-goods; approval chain SalesPlanner→SalesManager with per-transition role gates inside shared PUT endpoints
- Version-pinned pricing: flights pin rate card id+version+weekly rate at hold creation; later card edits never reprice existing flights
- Compensating invariants pinned as formulas: forward-calendar occupancy restored exactly after create+RELEASE; campaign.contracted_cents restored exactly after confirm+CANCEL with the fee (575000 at the 9-day 50% tier) quarantined in a separate accumulator
- Hold-first booking flow (all flights created HELD with 72h TTL; confirm gated on campaign approval, advertiser credit with `<=` boundary, and campaign-version OCC) — this is what makes the temporal, fiscal, and concurrency mechanics interlock

## Step 3: Copy Shared Files — 2026-08-13T11:22:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1467_out_home_billboard_inventory_booking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T11:40:00.000Z

All verifications pass. The PRD is complete and shipped.

---

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1467_out_home_billboard_inventory_booking/workspace/PRD.md` — 340 lines.

**Sections produced:**
- §1 Introduction (2 paragraphs: business context + determinism/clock angle)
- §2 Global Specifications — 11 subsections: 2.1 Roles & headers, 2.2 Response structure (byte-verbatim from `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination, 2.4 Common resource properties, 2.5 Logical clock & 4-step deterministic sweep, 2.6 Money/impressions/rounding discipline, 2.7 Booking posture & derived permit state, 2.8 Nested retrieval & not-found family, 2.9 Validation pipeline (14 families in scaffold priority order with masking semantics), 2.10 OCC (3 rules), 2.11 Segregation of duties
- §3 Business Logic — 9 subsections organized by lifecycle: 3.1 Rate cards & faces, 3.2 Permits & suspension cascade, 3.3 Maintenance work orders, 3.4 Advertisers/credit/campaigns, 3.5 Flight holds/pricing/availability/discounts/cancellation, 3.6 Artwork & posting verification, 3.7 Live/holdover/completion, 3.8 Impressions accounting, 3.9 Make-goods & settlement
- §4 Endpoint table (41 endpoints, 4 columns only); §5 Error catalogue (32 errors, 2 columns only)

**Coverage notes (mechanically verified):**
- Contract 1 Field-Name Coverage: 80/80 entity fields, 57/57 endpoint input identifiers present in backticks; 0 missing. (An initial false-negative was traced to a regex letting tokens span newlines — code fences broke backtick parity; corrected and re-verified.)
- Contract 2 Rule Coverage: all 12 state machines' transitions rendered with preconditions + error IDs + side effects (including sibling symmetry: BOOKED/ART_CLEARED cancel parity, AVAILABLE/UNDER_MAINTENANCE suspension parity, triple revocation sources); all 7 calculations in precise prose (pinned weekly-rate round-once rule, per-flight-then-sum discount order with observable confirm ordering, holdover 1.10 premium variant, AUDIENCE_MEASURED-supersession replay, per-reason make-good waterfall with gross cap, equality-allowed loop capacity, dual committed/forward calendars with merge rules); all 14 validation families ordered in §2.9 prose; all 3 OCC rules with write-endpoint + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; all endpoint side effects (face version bump on flight creation, cascade chains permit→face→flight→campaign, successor completion cascade with end_date/created_at ordering); all 32 error IDs appear in §2/§3 prose; all 42 state values, all enum values, all 9 roles with opaque-identity prose; all constants embedded (72h hold, 64-second loop, 1–16 slots, 30-day renewal window, 1.12 illumination factor, 0.15/0.90 credit constants, 5M/15M-cent tiers, 28/14-day cancellation tiers).
- Contract 3 §3 Path Purity: 655 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos (paths appear only in §2.10 and §4, which is permitted).
- No pseudocode/operator syntax; the single "about" hit is prepositional ("error about its payload"), not a quantity hedge.

**Zero-Silence Rule adjudications:**
1. **Supersede-target permit state violation** — scaffold requires the referenced permit be ACTIVE/RENEWAL_PENDING but nominates no error ID; PRD states the precondition without inventing an error binding (the sibling "current permit exists" case is bound to `ERR_INVALID_STATE` per the catalog).
2. **Manual make-good limited to UNDER_DELIVERY on COMPLETED flights** — scaffold gives no error ID for violations; stated as a capability boundary, no code invented.
3. **Work-order `COMPLETED` is listed terminal yet has a `COMPLETED → REOPENED` exit** — PRD resolves the tension explicitly: terminal states reject all mutations "except where a state machine explicitly defines an exit — the work-order reopen cycle is the sole such exception."
4. **Duplicate `face_code`** — catalog condition text assigns it to `ERR_INVALID_REQUEST` (400) while validation row 12 shows family status 409; the catalog's per-ID mapping was treated as authoritative (400).

## Step 5: Generate Unit Tests — 2026-08-13T12:33:00.000Z (recovered)

RESUME RUN recovery note: the prior pipeline run was terminated before it could record this step's summary in the worklog, but the on-disk artifacts were verified complete by the resuming orchestrator — all 10 `test_helpers/` modules (`__init__`, `types`, `api_client`, `api_errors`, `assertions`, `constants`, `factories`, `fixtures`, `test_users`) and 7 `test_suite/` files (`conftest.py` + `test_01`…`test_07`) parse cleanly under `python3 -m py_compile`; 72 test functions each carry exactly one `Design: <Difficulty|Corner>/...` tag (53 unique instances: 18 difficulty ×2 test functions each, 36 corner-tagged); no file shows truncation (final test file ends mid-suite-complete, all files compile). Artifacts kept and reused as-is per the resume contract; original subagent summary lost with the terminated run.

## Step 6: Generate Implementation — 2026-08-13T12:18:00.000Z (recovered)

RESUME RUN recovery note: the prior pipeline run was terminated before it could record this step's summary in the worklog, but the on-disk artifacts were verified complete by the resuming orchestrator — `workspace/implementation/` contains `app.py`, `start.sh` (executable, conditional-dependency-install + foreground `exec python3 app.py`), `requirements.txt`, and the full module set (`db`, `errors`, `middleware`, `response`, `util`, `calc`, `domain`, `serializers`) plus 12 route modules under `routes/` (rate_cards, faces, permits, work_orders, advertisers, campaigns, flights, artwork, postings, make_goods, clock_routes). All files parse cleanly under `python3 -m py_compile`. Artifacts kept and reused as-is per the resume contract; original subagent summary lost with the terminated run.

## Step 7: Run Tests and Iterate — 2026-08-13T12:45:00.000Z

- **Iterations run:** 1 (single 8-round parallel stability sweep; all 8 rounds completed with `passed == total`).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

The recovered pipeline artifacts (test suite of 72 tests across 7 files, and the Flask implementation in `workspace/implementation/`) were already green: every round of the 8-round concurrent sweep under `--isolation per-test-server` reported 72/72 passed, 0 failed, with no flakiness signal across rounds. No diagnostic step was triggered, so no deletions or edits were required.

## Step 8: Finalize PRD — SKIPPED — 2026-08-13T12:46:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-08-13T13:20:00.000Z

Step 9 complete. `PRD_COMPLETED.md` written to `/home/ubuntu/github/CodingPRD/tasks/task_1467_out_home_billboard_inventory_booking/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD.md` 340 lines / 56,294 chars → `PRD_COMPLETED.md` 340 lines / 60,467 chars (**+4,173 chars, +0 lines**). All 19 changes are in-paragraph inserts/revisions — no new sections, no new paragraphs.

**Counts:** 18 ambiguity-pins, 1 mismatch-revision.

**Changes (one per bullet):**

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the wall clock; resource `created_at`/`updated_at` and rule-driven timestamps read the logical clock — response.py:16, util.py:42-43, db.py:28
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range integers clamped (`limit`→1–100, `offset`→0); `total_count` = full filtered count; `has_more` true iff items remain beyond page; `created_at` ties broken by creation order; unknown `status` filter yields empty page — response.py:32-67, faces.py:173-176
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — db.py:33
- §2.5 — insert — ambiguity — `current_utc` echo rendered without fractional digits on whole-second readings, else 3 fractional digits — util.py:34-39, clock_routes.py:25
- §2.8 — insert — ambiguity — body-carried foreign keys (`advertiser_id`, `face_id`, `campaign_id`, `rate_card_id`, `flight_id`, `predecessor_flight_id`, `supersedes_permit_id`) get the same typed 404s, checked in narrative order before shape validation — flights.py:34-45, permits.py:30-35, campaigns.py:31-33, work_orders.py:36-38, artwork.py:34-36, postings.py:33-35, make_goods.py:33-35
- §2.9 — insert — ambiguity — a `status` naming no defined transition → `ERR_INVALID_STATE` regardless of role; same-status writes are no-op successes on rate cards/faces/advertisers/campaigns but `ERR_INVALID_STATE` on permits/work orders/flights/artwork orders/posting records/make-goods — rate_cards.py:88, faces.py:106, advertisers.py:62, campaigns.py:105, permits.py:113-142, flights.py:196-198, artwork.py:116-118, postings.py:96-100, make_goods.py:84-86
- §3.1 — insert — ambiguity — rate-card monetary/threshold fields are non-negative integers, percentage fields non-negative numbers, on create and update — rate_cards.py:36-41, 74-83
- §3.1 — insert — ambiguity — face `daily_traffic_count` ≥ 0 integer, `width_inches`/`height_inches` ≥ 1 — faces.py:38-40
- §3.2 — insert — **mismatch** — at permit filing the supersession-shape checks (PRD family 12) run before the expiry-against-the-clock rule (family 9), so a supersession violation surfaces `ERR_INVALID_STATE` even with a past `expires_on`; PRD's pipeline had family 9 masking family 12 — permits.py:51-65
- §3.4 — insert — ambiguity — a campaign update may carry both `status` and `billing_status` (status applied first); carrying neither → `ERR_INVALID_REQUEST` — campaigns.py:99-100, 105-178
- §3.5 — revise — ambiguity — availability inquiry requires `from_date`/`to_date`; missing/unparsable dates or `to_date` < `from_date` → `ERR_INVALID_REQUEST` — faces.py:198-201
- §3.5 — insert — ambiguity — confirm re-runs overlap/loop-capacity checks excluding the flight being confirmed — flights.py:277-284
- §3.6 — insert — ambiguity — `SHIPPED`→`DELIVERED` records two modifications (status + charge stamp), so order `version` advances by 2 — artwork.py:122-128
- §3.6 — insert — ambiguity — verification requires the flight in `ART_CLEARED` or `MISSED` (else `ERR_INVALID_STATE`); an on-time `posted_on` moves the flight to `LIVE` from either state with no missed-posting make-good and `missed_days` unchanged — postings.py:122-136
- §3.7 — insert — ambiguity — "successor" at end-of-flight resolution means any other flight on the same face holding a `VERIFIED` posting record, regardless of `predecessor_flight_id` chaining — domain.py:356-361
- §3.8 — insert — ambiguity — `impressions` must be a non-negative integer; the append returns `201 Created` carrying the updated flight object — flights.py:367, 381
- §3.8 — revise — ambiguity — `delivery_ratio` is 0 also when `estimated_impressions` is 0 (not only when no entries exist) — calc.py:84-86
- §3.9 — insert — ambiguity — auto `UNDER_DELIVERY` evaluation is idempotent: a fresh system proposal only while none sits in `PROPOSED`/`APPROVED`/`APPLIED`; `REJECTED` and manual proposals never block — domain.py:114-124
- §3.9 — insert — ambiguity — a manual `UNDER_DELIVERY` proposal filed with no shortfall (or `estimated_impressions` 0) is still created with `credit_cents` 0 — make_goods.py:48-50

Everything else in the implementation — endpoint/role table, sweep order and boundaries, pricing/discount/cancellation/holdover/make-good formulas, rounding order, state machines, OCC guards, segregation of duties, error catalogue — matched the PRD as written and required no change.
