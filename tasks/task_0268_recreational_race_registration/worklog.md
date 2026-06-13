# Worklog — task_0268_recreational_race_registration

## Step 1: Create Task Directory — 2026-06-09T12:50:42.000Z

Created pre-allocated task directory `tasks/task_0268_recreational_race_registration/` with `workspace/` subdirectory. Index 0268 used verbatim (pre-allocated; no auto-increment scan performed — five parallel runs claiming 0264-0268). Difficulty target: Expert.

## Step 2: Generate Scaffold — 2026-06-09T13:14:24.000Z

All three scaffold artifacts are complete, self-consistent, and pass `scaffold_lint.py` with a clean verdict.

## Summary

Generated three scaffold artifacts for **Recreational Race Registration (5K/marathon)** at **Expert** difficulty in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0268_recreational_race_registration/`:

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** quota_allocation primary + pricing_engine secondary; hybrid topology; branching state-machine shape; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Entities (12):** Participant, Event, Distance, Wave, PricingTier, Registration, WaitlistEntry, FundraisingPledge, TransferRequest, BibAssignment, PacketPickup, ResultRecord.

**State machines (7):**
- Event.status: DRAFT → OPEN → CLOSED → RESULTS_POSTED (+ CANCELLED with depth-3 cascade)
- Registration.status: PENDING_PAYMENT → {CONFIRMED, WAITLISTED} → BIB_ASSIGNED → FINISHED, plus CANCELLED / TRANSFERRED / DEFERRED (self-referential deferral cycle)
- WaitlistEntry.status: QUEUED → OFFERED → {CLAIMED, EXPIRED, DECLINED} / WITHDRAWN (branching FIFO promotion)
- TransferRequest.status: PROPOSED → {ACCEPTED, REJECTED, CANCELLED}
- ResultRecord.status: PROVISIONAL → {OFFICIAL, DQ}; OFFICIAL → DQ
- FundraisingPledge.status: PLEDGED → SETTLED → VOIDED
- PacketPickup.status: ISSUED → VOIDED

**Counts:** 6 calculations (tiered pricing, refund with pinned rounding order, dual-variant fundraising progress, corral seeding, gun/chip timing, deferral credit), 19 validations (priority-ordered), 65 endpoints (includes flat FK-reverse-reachability filtered lists + a `/_clock/set_current_utc` test-driving endpoint), 19 error codes, 4 roles (Participant entity_backed; RaceDirector/PacketStaff/TimingOfficial opaque), plus 2 OCC concurrency rules on Distance.version.

**§1.8 difficulty design:** all 9 Difficulty Rules × 2 instances = **18 instances**, each grounded in §1.1–§1.7 with executable `setup_api_calls`/`trigger` chains and computed literal asserts (e.g., amount_due 4811, refund 3974, deferral credit 4000, pace 2400).

**§1.9 corner design:** **36 instances** (32 active with full test recipes + 4 `excluded_because:` stubs referencing named §1.8 instances) spanning entities, state machines, calculations, validations, endpoints, RBAC, cross-cutting layers, and consistency model.

**Lint:** `python3 scaffold_lint.py` → `VERDICT: clean lint` (65 endpoints, 12 entities, 18 §1.8 + 32 §1.9 instances, 551 calls scanned, 0 violations). All grounds references resolve; no forbidden concurrency vocabulary; no §1.8/§1.9 name collisions.

One scenario gap was found and fixed during generation: `Registration.fundraising_minimum_cents` referenced a Distance charity floor that didn't exist, so a `charity_fundraising_minimum_cents` field was added to Distance (and its create endpoint input).

## Step 3: Copy Shared Files — 2026-06-09T13:14:46.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0268_recreational_race_registration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-09T13:22:12.000Z

All checks pass. The PRD is complete and verified against the scaffold.

## Summary

Generated `workspace/PRD.md` — a 294-line prose PRD for the Recreational Race Registration API.

### Section structure
- **§1 Introduction** — 3 paragraphs (capacity/waitlist tension, commercial+operational scope, concurrency rationale)
- **§2 Global Specifications** — 10 domain-derived subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination (+ list filters), 2.4 Common Properties/Versioning, 2.5 OCC, 2.6 Capacity/Sub-Capacity/Waitlist, 2.7 Monetary Precision/Rounding, 2.8 Hierarchical Consistency/Cascades (+ test clock), 2.9 Nested Retrieval/Referential Validation, 2.10 Validation Ordering
- **§3 Business Logic** — 9 lifecycle-grouped subsections: event setup, registration creation/pricing, payment/waitlist, cancel/transfer/defer, charity/fundraising, bib/corral, packet pickup, timing/finishing, event cancellation
- **§4 Endpoint Definitions** — 4-column table, 65 rows (all 65 scaffold endpoints)
- **§5 Error Code Catalogue** — 2-column table, 19 rows (all 19 errors)

### Hard Contract reports — all PASS
- Contract 1 (Field-Name Coverage): 60/60 entity fields, 32/32 request inputs, 18/18 query params, 12/12 path params. PASS
- Contract 2 (Rule Coverage): 19-validation priority chain rendered as ordered prose in §2.10; 2 OCC rejections; all state-machine transitions; 6 calculations reconstructible step-for-step; sibling-branch symmetry verified. PASS
- Contract 3 (§3 Path Purity): 312 backtick tokens scanned, 0 paths/methods leaked into §3 prose. PASS

All scaffold entities, state machines, calculations (constants 0.029, 0.20, 0.10/0.05, 0.15, 1500 cents, BIB_START 100, 24h offer TTL), validations, 65 endpoints, 19 errors, 4 roles covered in prose. §2.2 envelope verbatim. No design YAMLs or sibling tasks read.

## Step 5: Generate Unit Tests — 2026-06-09T13:39:53.000Z

All 68 tests collect cleanly. Generation is complete.

## Summary

Generated complete test infrastructure for **task_0268_recreational_race_registration** purely from the four input files plus the unit-test-generator skill spec.

**Test files: 6** (under `test_suite/`), plus `conftest.py`:
- `test_01_event_setup_and_access.py` — 10 tests (participant create, not-found, pricing-tier immutability/duplicate, open precondition, pagination, RBAC)
- `test_02_registration_pricing.py` — 11 tests (required fields, defaults, computed amount, no-active-tier, charity zero base, combinatorial discount, dual-variant tier flip, refund rounding order)
- `test_03_capacity_and_waitlist.py` — 12 tests (initial state, re-confirm invalid, capacity boundary, version increment, OCC stale confirm/claim, waitlist decline/claim, promotion cascade, expiry)
- `test_04_transfer_defer_cancel.py` — 8 tests (cancel lockdown, ownership, transfer accept, deferral self-reference + slot free, defer-same-event, event-cancel cascade + version)
- `test_05_bib_corral_fundraising.py` — 13 tests (fundraising gate dual-variant + boundary, corral seeding, wave full + room, priority-pair safety, conserved-quantity invariants)
- `test_06_results_packet_and_state_deps.py` — 14 tests (timing calc, invalid timing, DQ branch, cross-entity confirm/finish deps, state-vs-temporal priority, window bound, relation mismatch, packet eligibility)

**Total tests: 68** — each carries exactly one verbatim `Design:` tag (68 tags, no untagged/dual-tagged).

**Traceability:**
- **Queue A (Difficulty §1.8): 36 tests** covering all **18** difficulty instances (9 rules × 2), every instance with ≥2 tests.
- **Queue B (Corner §1.9): 32 tests** covering all **32** non-stub corner instances, ≥1 test each.

**Skipped: 0 instances.** All four `excluded_because:` stubs were correctly NOT translated; their `difficulty_instance` cross-references all resolve to real §1.8 instances. Every targeted rule has verbatim, uniquely-derivable PRD prose (~45 citations spot-verified).

**test_helpers/ files written (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

Key correctness: `PricingTier` TypedDict/assertion omit `updated_at`/`version` (common_fields:false); entity-backed `Participant` uses `make_participant_headers(id)` for ownership-gated calls, three opaque roles use shared constants; literal expected values (5660/7203/4811/136/3974/4000, corral A bibs 100/101, timing 12130/12000/2400) copied verbatim. No skip/xfail markers, no scaffold leakage.

## Step 6: Generate Implementation — 2026-06-09T13:39:53.000Z

All modules compile, no seeding, no float arithmetic in money calculations (Decimal throughout; `distance_km` passed via `str()` into Decimal).

## Summary

Built a complete Python + Flask implementation at `workspace/implementation/`.

### File structure
```
implementation/
├── start.sh              # guarded foreground launcher (reads $PORT, binds 0.0.0.0, exec)
├── requirements.txt      # flask==3.0.3
├── app.py                # entry point, blueprint registration, error handlers, app.run
├── db.py                 # in-memory store (one dict per entity) + logical Clock
├── errors.py             # ApiError + error_id/http_status catalogue (19 errors)
├── response.py           # success/array/error envelope helpers
├── middleware.py         # auth (X-User-ID/X-User-Role), RBAC, ISO8601 parse/format
├── routes/               # participants, events, distances, registrations, waitlist,
│                         #   pledges, transfers, packets, bibs, results
└── services/             # calculations, store (serialize/paginate/computed),
                          #   validate, waitlist (promotion)
```

### Storage model
Pure in-memory Python dicts keyed by UUID, one per entity type, on a single global `DB` created **empty at import**. No seeding. A logical `Clock` (overridable via `POST /_clock/set_current_utc`) drives all time-gated logic and stamps timestamps; a monotonic `_seq` provides deterministic tie-breaking when `created_at` collides.

### Endpoints
All endpoints from PRD §4 implemented (reported 67): participants (2) + clock (1), events (6), distances/waves/pricing-tiers (11), registrations + transitions + FK sub-lists (14), waitlist (6), pledges (5), transfer-requests (7), packet-pickups (4), bib-assignments reads (4), results (7).
[NOTE: Step 4 PRD reports 65 §4 rows; impl reports 67 — count discrepancy to be surfaced/resolved by Step 7 tests if behavioral.]

### State machines encoded
Event, Registration (PENDING_PAYMENT forking CONFIRMED/WAITLISTED + BIB_ASSIGNED/CANCELLED/TRANSFERRED/DEFERRED/FINISHED), WaitlistEntry (FIFO promotion by created_at), TransferRequest, ResultRecord (PROVISIONAL→OFFICIAL→DQ), FundraisingPledge, PacketPickup. Cascades bump version/updated_at.

### Calculations (Decimal)
Tiered pricing (pinned 8-step; provisional vs final variants; CHARITY base 0; verified 8232), refund (fee rounded independently; verified 6800), deferral credit `max(net−1500,0)`, fundraising totals (provisional vs settled-only), corral assignment (qualifying_time ASC null-last, created_at tie-break, `rank // corral_capacity`→A/B/C), bib numbering (sequential from 100), timing (gun/chip + round_half_up pace; verified 284).

### Confirmations
- `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground; guards pip install behind import check.
- No data seeded — all list endpoints return total_count=0 on fresh boot.
- Response envelope, auth headers, OCC field (`expected_distance_version`), pagination (limit 10/min1/max100/offset0), 19 error IDs match PRD. Validation priority ordering confirmed.

## Step 7: Run Tests and Iterate — 2026-06-09T13:44:56.000Z

All 8 parallel rounds pass cleanly (68/68 each). Exiting per the protocol.

## Summary

**Iterations run:** 2 (initial sweep + 1 fix sweep).

**Tests deleted:** None. The single failure traced to a test-assertion mistranslation that was fixable to be more PRD-faithful, not a PRD-silence/non-derivability case.

**Fixes applied to test_suite/:**
- `test_suite/test_02_registration_pricing.py`, `test_amount_due_group_and_promo_discount_combined`: changed the assertion `processing_fee_cents == 136` to `processing_fee_cents == 0` at registration-creation time. PRD §3.2 states verbatim: "The provisional `amount_due_cents` is only an estimate: no charge is captured at creation, `amount_paid_cents` and `processing_fee_cents` remain 0." The `136` figure is the fee *component embedded inside* `amount_due_cents` (discounted base 4675 + fee 136 = 4811), not the stored `processing_fee_cents` field, which the PRD pins to 0 until payment confirmation. The companion test `test_amount_due_solo_no_promo_baseline` already asserts the identical PRD-faithful rule (`processing_fee_cents == 0` at creation), and the implementation (`routes/registrations.py:108`) correctly sets the field to 0 at creation and to the captured fee only at confirm (`:196`). The meaningful `amount_due_cents == 4811` assertion (the combined group+promo discount-cap check this test exists to exercise) was preserved unchanged.

**Fixes applied to implementation/:** None. The implementation was already PRD-faithful for this rule.

**Stability note:** The lone failure was deterministic (failed identically in all 8 rounds of the first sweep), not timing-sensitive; no flakiness was observed. After the fix, all 8 concurrent rounds pass 68/68.

## Step 8: Finalize PRD — 2026-06-09T13:46:59.000Z

Done.

## Summary

**Output:** `workspace/PRD_FINALIZED.md` — produced via the step-0 `cp`, **identical to PRD.md** (verified `diff -q` → IDENTICAL).

**Line counts:** PRD.md 294 lines / PRD_FINALIZED.md 294 lines — **0% delta, no edits**.

**Change log:**
- **No edits — PRD already pins the behavior.** The sole Step 7 item was a test-assertion mistranslation, not a PRD-silence or PRD/impl divergence. PRD §3.2 (line 150) states verbatim: "no charge is captured at creation, `amount_paid_cents` and `processing_fee_cents` remain 0." The implementation already complies at `routes/registrations.py:108` (sets `processing_fee_cents: 0` at creation) and `:196` (captures fee only at confirm). The `136` figure was the fee component embedded inside `amount_due_cents` (4675 + 136 = 4811), never the stored field. Nothing in the PRD needed pinning.

**Pre-edit search log (no-edit verdict enumeration):**
- **(a) Subject:** stored `processing_fee_cents` / `amount_due_cents` fee component / `amount_paid_cents` across the registration lifecycle.
- **(b) Impl paths enumerated** (grep over `implementation/*.py`, then read): `routes/registrations.py:106-108` (creation: due=estimate, paid=0, fee=0), `:195-196` (confirm capture), `routes/waitlist.py:95-99` (claim capture), `routes/transfers.py:105-107` (transfer reg = 0), `routes/registrations.py:379-381` (deferral reg = 0), `:216` & `routes/events.py:130` (refund reads stored fields), `:355` (deferral credit reads same), `services/calculations.py:46-109` (pinned formulas). All consistent with existing PRD §2.7/§3.2/§3.3/§3.4/§3.9 prose.
- **(c) Wording adjustment:** none — every enumerated path already accurately described; no edit made.

## Step 9: Complete PRD — 2026-06-09T13:53:20.000Z

Done. Walked the implementation exhaustively (app/middleware/response/errors/db, services for calculations/store/validate/waitlist, all 10 route modules) and cross-referenced PRD prose. Almost all behavior already pinned uniquely; made 7 minimal in-paragraph edits to close genuine silences and one mismatch.

## Summary

- Source: `PRD_FINALIZED.md` (identical to `PRD.md`) — 294 lines, 45,782 chars
- Result: `PRD_COMPLETED.md` — 294 lines, 47,901 chars (char delta +2,119; no line-count change, all edits in-paragraph)
- Counts: 6 ambiguity-pins, 1 mismatch-revision. No new sections/paragraphs, no invented behavior.

### Changes
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (limit→[1,100], offset→≥0); non-integer values yield `ERR_INVALID_REQUEST` — `services/store.py:128-151`
- §2.6 Capacity — insert — ambiguity — `charity_capacity` > `capacity_total` rejected with `ERR_INVALID_REQUEST` — `routes/distances.py:32-33`
- §3.1 Pricing Tiers — revise — mismatch — `base_price_cents` minimum is 0 (zero accepted), overriding §2.10's blanket "amounts at least 1" for this field — `routes/distances.py:143`
- §3.3 Confirm Payment — insert — ambiguity — confirming when owning event is not `OPEN` yields `ERR_REGISTRATION_CLOSED` — `routes/registrations.py:156-157`
- §3.4 Transfers — insert — ambiguity — accept's error mapping (`ERR_INVALID_STATE`/`ERR_REGISTRATION_CLOSED`) + new-registration field shape (inherits event/distance/wave + qualifying_time, resets party_size=1, promo_code=null, fundraising_minimum_cents=0, monetary=0, deferred_to_registration_id=null) — `routes/transfers.py:88-110`
- §3.4 Deferral — insert — ambiguity — target distance = first label-matching distance, wave on it, inherited fields, fundraising_minimum derived from target distance, monetary fields stay 0 (no pricing at deferral) — `routes/registrations.py:341-385`
- §3.6 Bib & Corral — insert — ambiguity — re-ranking recomputes prior bibs' `corral` in place without bumping version/updated_at; existing bib_numbers stable; only newly assigned registration's wave bumps `Wave.version` — `routes/registrations.py:288-320`

Tests used only as auxiliary cross-reference; never treated as authority.

---

## Pipeline Complete — 2026-06-09T13:53:20.000Z

All 9 steps finished. Final 8-round parallel stability sweep: **68/68 passing in all 8 rounds**. Artifacts present: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (+7 edits), test_helpers/ (9 files), test_suite/ (6 files + conftest, 68 tests), workspace/implementation/ (Python+Flask, in-memory).
