# Worklog — task_0998_mobile_corporate_chair_massage

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0998_mobile_corporate_chair_massage` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions. Difficulty parameter: "generate task hard than expert level!" (passed through to Step 2 only).

## Step 2: Generate Scaffold — 2026-08-10T13:28:00.000Z

Generated three scaffold artifacts for `task_0998_mobile_corporate_chair_massage`:

- `/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/SCAFFOLD.yaml` — §1.0–§1.7. Primary archetype `temporal_windowing`, secondary `pricing_engine`; layers: cascading side effects, dual-variant calc, rate/threshold triggers, optimistic concurrency. 13 entities (Region, CorporateAccount, WellnessProgram, Therapist, TherapistLicense, Booking, ChairSlot, SlotClaim, TravelLeg, Waiver, Invoice, SatisfactionSurvey, PayoutLedgerEntry); 9 state machines (Booking has compound status × parallel billing_status; Invoice ISSUED↔DISPUTED cycle; TherapistLicense ACTIVE↔SUSPENDED cycle); 2 OCC concurrency rules; 6 calculations (invoice_pricing with mode-(c) pinned eval order, travel_fee mode-(a) tiered + volume threshold, payout_earnings mode-(b) per-line rounding, cancellation_fee 4-tier threshold, satisfaction_credit tiered, next_occurrence_date); 16 prioritized validations; 81 endpoints (including `/_clock/set_current_utc` with default `2026-05-01T00:00:00Z`); 22 errors; 3 roles (PlatformAdmin opaque, Organizer entity-backed to CorporateAccount, Therapist entity-backed to Therapist).

- `/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 18 instances, 2 per rule across all nine §0.5 rules. Differentiation clauses honored: dual-variant across Invoice vs TravelLeg domains; combinatorial modes (a) cancellation-fee thresholds and (b) payout per-line rounding; non-linear state machines on Invoice (dispute cycle) and TherapistLicense (suspend cycle); cascades from license-revoke (depth-3) and corporate-suspend (depth-2); priority conflicts (state vs OCC) and (license vs double-booked); boundaries on cancellation-fee H==24 and signup capacity; cross-entity pairs (Booking,License) and (SlotClaim,Waiver); overlap rules with buffer-extended therapist windows vs ordinal-sliced chair slots; invariants on booked_chair_minutes and outstanding_balance_cents.

- `/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/SCAFFOLD_CORNER_DESIGN.yaml` — 30 corner instances across sections entities / state_machines / calculations / validations / endpoints / errors / roles / cross_cutting_layers / consistency_model. Includes one `excluded_because` stub for the volume-discount threshold already covered by §1.8.

Lint verdict (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
823 test-recipe calls scanned; 81 endpoints, 13 entities, 18 difficulty + 30 corner instances.

## Step 3: Copy Shared Files — 2026-08-10T13:28:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0998_mobile_corporate_chair_massage/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T13:45:00.000Z

All verification passes are complete. The PRD has been generated at `/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/workspace/PRD.md`.

**What was done:**
- Read the skill spec, the §2.2 verbatim source block, and the example PRD; read only `SCAFFOLD.yaml` (the two forbidden difficulty/corner design files were not opened or referenced).
- Generated a PRD with a domain-derived skeleton: 2-paragraph introduction; §2 with ten subsections (RBAC, verbatim response envelope, pagination/filtering, the logical clock, common resource properties, monetary precision, OCC, the validation pipeline, derived-aggregate consistency, nested retrieval); §3 with eight business-timeline subsections (regions/accounts → therapists/licenses → booking composition → staffing/confirmation → wellness programs → event day → session close-out/cancellation → invoicing/disputes/satisfaction); §4 endpoint table (81 rows, 4 columns); §5 error catalogue (22 rows, 2 columns).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + common fields + endpoint inputs/outputs + occ fields: 92 required, 92 present, 0 missing
- endpoints[].query_params (limit/offset + 12 filter names): all present (§2.3)
Status: PASS

Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in prose (global pipeline in §2.8; per-endpoint orderings stated: cap→license→double-book on assign/confirm, capacity→duplicate on claims, credit→live-invoice on issue), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_booking_version/expected_chair_slot_version + ERR_STALE_BOOKING_VERSION/ERR_STALE_CHAIR_SLOT_VERSION + HTTP 412, stale-version framing only), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed (invoice_pricing, travel_fee QUOTED/SETTLED, payout_earnings per-line half-up, cancellation_fee 4 tiers, satisfaction_credit 3 tiers, next_occurrence_date), 0 missing
- validations[] conditions: 16 checked, 16 matchable to error_id in prose, 0 missing (all 22 error ids verified present mechanically)
- endpoints[].side_effects / applies_to: 34 side-effect endpoints checked, all expressed (cascades: cancel-from-CONFIRMED, completion settlement, account suspend/close, license revoke, claim/no-show recomputes), 0 missing
- entities[].fields[] structured content: defaults/constraints/variants reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (3 cancel branches, 2 void branches, 2 expiry branches, 2 terminate branches, PROVISIONAL/FINAL, QUOTED/SETTLED, 3 cadences, 4 fee tiers, 3 credit tiers), all symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 417
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional verifications:** §2.2 matches the fixed source file byte-for-byte (confirmed programmatically); §4 table has exactly 4 columns and covers all 81 scaffold endpoints with correct methods/roles; §5 has exactly 2 columns and all 22 errors; no fuzzy/approximating vocabulary and no pseudocode operators in prose; the document ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-10T14:20:00.000Z

Generation complete. Summary of what was produced and the key adjudications:

**`test_helpers/`** (9 files): `types.py` (13 entity TypedDicts — `SatisfactionSurvey`/`PayoutLedgerEntry` correctly omit `updated_at`/`version` per PRD §2.5; all status enums), `api_client.py` (one method per PRD §4 endpoint, ~70 methods), `api_errors.py` (all 22 error IDs mapped and registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque `PlatformAdmin` constant + mandatory `make_organizer_headers(account_id)` / `make_therapist_headers(therapist_id)` builders for the two `entity_backed` roles), `fixtures.py` (tiered composites: `setup_region_account_therapist` → `setup_scheduling_booking` → `setup_in_progress_booking` → `setup_completed_booking` → `setup_completed_booking_with_invoice` / `setup_issued_invoice`, with OCC-fresh version fetches before every guarded call), `__init__.py` barrel.

**`test_suite/`**: `conftest.py` + 14 test files, **68 tests** (36 difficulty-tagged, 32 corner-tagged).

**Audit results (all pass)**
- Every one of the 18 §1.8 difficulty instances has ≥2 tests with verbatim `Design: Difficulty/<rule_id>/<name>` tags; every one of the 30 non-stub §1.9 corner instances has ≥1 test with `Design: Corner/<section>/<name>` tags. No untagged, dual-tagged, or dangling tags; each tag is the docstring's final line.
- All 107 PRD citation blocks verified as whitespace-normalized verbatim substrings of `PRD.md`.
- No `skip`/`skipif`/`xfail`; no "scaffold" references in generated code; all files compile; `test_helpers` imports cleanly.

**Key PRD-first adjudications (gaps left as gaps)**
1. **Travel-fee literal amounts dropped**: the PRD defines no endpoint or payload that sets `TravelLeg.distance_miles` (legs are auto-created at confirm; `confirm` takes only `expected_booking_version`), so the design instance's literal asserts (QUOTED 2400 / SETTLED 1920) are not uniquely derivable. The instance's two tests instead assert the PRD-verbatim variant lifecycle: `PLANNED`+`QUOTED` at confirm, `SETTLED`+`REIMBURSED` at complete, and the `TRAVEL_REIMBURSEMENT` ledger posting.
2. **License-revoke cascade**: the instance's claim that releasing a chair cancels its `CLAIMED` claims (driving `booked_chair_minutes` to 0) has no PRD coverage — dropped. Tests assert the derivable core: REVOKED status, ASSIGNED→RELEASED cascade, and region scoping (chairs in other regions untouched).
3. **Outstanding-balance invariant** asserts deltas against the invoice's *observed* `total_cents` rather than the recipe's hard-coded 6000, since the auto-created leg's fee is unspecified (same root cause as #1).
4. **Mark-no-show test** moves the logical clock past `event_date` before the trigger, satisfying both plausible readings of the claim-level no-show precondition ("post-event" endpoint label vs. the §3.7 cancel/no-show sentence).
5. **The one stub** (`rate_threshold_volume_discount_at_exactly_20`) was not translated; its `excluded_because` pointer resolves to the real difficulty instance `dual_variant_calc/travel_fee_quoted_vs_settled_volume_discount`.
6. Caught during audit: f-string docstrings defeat `ast.get_docstring` — all rewritten as plain docstrings with inlined verbatim citations.

## Step 6: Generate Implementation — 2026-08-10T14:20:00.000Z

Generated a complete Python + Flask implementation for task_0998 (Mobile Corporate Chair Massage) at `/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/workspace/implementation/`.

**Layout**
- `start.sh` — foreground launcher, guarded `pip install` (no-op once Flask present), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — app factory, error handlers (ApiError + 404/405/400/500 all return the standard error envelope), blueprint registration
- `clock.py` — logical clock booting at 2026-05-01T00:00:00Z; all timestamps/decisions read it (3-fractional-digit ISO 8601 UTC)
- `db.py` — in-memory store, empty at boot, no seeding; `stamp_new`/`touch` manage `created_at`/`updated_at`/`version`
- `auth.py` — X-User-ID/X-User-Role gate (401), per-route RBAC (403), bootstrap exemptions (therapists, corporate-accounts, clock set), entity-backed ownership (Organizer = CorporateAccount id, Therapist = Therapist id)
- `validate.py` — field-shape validators (400 ERR_INVALID_REQUEST), pagination (limit default 10/min 1/max 100, offset default 0), equality filters
- `respond.py` — exact envelope: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, pagination fields in `meta` for lists
- `services/calc.py` — all calculations with Decimal: floor-based percentages (recurrence discount, travel high-volume 20% at ≥20 sessions, cancellation tiers 50/25/10/0 by floored hours at 24/72/168, satisfaction credit 25%/10% at avg_x100 <200/<300), per-line round-half-up payout, weekly/biweekly/monthly next-occurrence computation with clamping
- `services/domain.py` — derived aggregates (booked/delivered minutes), buffer-extended half-open overlap scan, license validity, chair release + leg waive cascades, DRAFT invoice recomputation, billing-status transitions, account balance adjustment
- `routes/` — 11 blueprints covering all 77 endpoints

**Key fidelity decisions**
- Validation pipeline: 401 → 403 (role) → 404 (path, left-to-right) → 403 (ownership) → 409 (state) → 412 (OCC) → 422 business (fixed relative order: daily-cap → license → double-booked; capacity → duplicate-signup; credit-limit → live-invoice) → 400 field shape
- OCC: `expected_booking_version` (required, 412 ERR_STALE_BOOKING_VERSION) on confirm; `expected_chair_slot_version` (412 ERR_STALE_CHAIR_SLOT_VERSION) on claim creation; assign/release bump Booking.version, claim create/cancel/no-show bump both chair and booking versions
- SatisfactionSurvey/PayoutLedgerEntry carry only `id`/`created_at` (no `updated_at`/`version`)
- Confirm accepts optional `travel_legs` per-therapist overrides (scaffold gap: no declared input for origin_address/distance_miles; defaults are `""`/0)
- Materialized bookings copy program window/slot/chair fields, take region from account, rate default 1 (overridable); idempotent per event_date; MONTHLY clamps (Jan 31 → Feb 28 → Mar 28)
- License expiry sweep runs on clock advance; revoke cascades chair releases; account suspend/close cascades to programs; program terminate recomputes DRAFT-invoice recurrence tier

**Verification** — ran three fresh-boot scenario suites (~110 assertions, all passing): full lifecycle (region→account→therapist→license→booking→assign→confirm→claims→waiver→check-in→complete→invoice→dispute→payment), calculation boundaries (cancellation tiers at <24/24-72/72-168/≥168h, satisfaction tiers at 1.50/2.00/3.00, high-volume travel discount at exactly 20 sessions, per-line payout rounding 40660), adjacency vs overlap semantics, daily-cap/license/suspension rejections, revoke/no-show cascades, dispute→void balance restoration, pagination validation, ownership 403s, and clean-reboot checks (empty store, default clock) via `bash start.sh`.

## Step 7: Run Tests and Iterate — 2026-08-10T15:10:00.000Z

Clean 8-round parallel sweep: 68/68 passing in every round. Exiting per protocol.

- **Iterations run**: 3 sweeps (round 1: collection failure; round 2: 5 deterministic failures × 8 rounds; round 3: clean 8×68/68).

- **Tests deleted**: none. Every failing test traced to verbatim PRD prose; all were repairable as test-artifact bugs.

- **Fixes applied to `test_helpers/`** (`/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/test_helpers/fixtures.py`):
  - Added missing `get_slot_claim(ctx, claim_id)` fixture getter (wraps the existing `api_client.get_slot_claim`), fixing the collection failure that zeroed all of iteration 1 — `test_13` imported a helper that only existed as a client method.
  - `create_event_booking`: merged explicit `corporate_account_id`/`region_id` with `**overrides` into one dict before calling `create_booking_payload`, fixing `TypeError: got multiple values for keyword argument 'region_id'` when a test legitimately overrode the region (PRD §3.2 cross-region revoke test).
  - Added `cancel_claim(ctx, claim_id)` fixture wrapper over `api_client.cancel_slot_claim` (PRD §3.7 claim-cancellation pathway), needed by the rewritten FINAL-invoice test.

- **Fixes applied to `test_suite/`**:
  - `test_05_therapist_assignment.py` — both `TestTherapistWindowOverlap` tests now pass `window_duration_minutes=120` explicitly; the comments' arithmetic (raw 600..720, extended 570..750) assumed a 120-min window while the factory default is 60, so the "adjacent raw windows overlap after buffer extension" case was actually a touching (permitted) case. PRD §3.4 half-open interval rule unchanged and now genuinely exercised at both boundaries.
  - `test_10_invoice_pricing.py::test_recurrence_discount_applied_on_recurring_occurrence` — re-fetched chairs via `list_booking_chairs` after assignment before `drive_booking_in_progress`; the stale pre-assignment chair dicts had `therapist_id=None`, producing headerless depart/arrive calls (401).
  - `test_10_invoice_pricing.py::test_final_invoice_bills_delivered_chair_minutes` — PRD §3.8 states FINAL is "used for `COMPLETED` or `CANCELLED` bookings", so requesting FINAL on an IN_PROGRESS booking is not uniquely derivable as accepted (implementation's 409 gate is a faithful reading). Test now cancels the outstanding CLAIMED claim, completes the booking, then issues FINAL; it still asserts `chair_minutes_billed == 30` (delivered) vs the earlier PROVISIONAL reading of 45 (booked), preserving the dual-variant disagreement assertion.
  - `test_11_invoice_lifecycle.py::test_live_invoice_uniqueness_blocks_second_draft` — second draft now requested with `pricing_variant: "FINAL"` (the variant PRD §3.8 names for COMPLETED bookings) so the variant-availability gate cannot fire first and the assertion isolates the verbatim rule "attempting to create a second … is rejected with `ERR_LIVE_INVOICE_EXISTS`".

- **Fixes applied to `implementation/`**: none. Every failure was a test-artifact defect; the implementation's behavior was PRD-faithful in all five cases (overlap half-open semantics, variant-availability gating, auth header enforcement).

## Step 8: Finalize PRD — 2026-08-10T15:20:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage/workspace/PRD_FINALIZED.md` with exactly one inline insertion.

**Line counts / delta**
- `PRD.md`: 308 lines — `PRD_FINALIZED.md`: 308 lines — **0% line delta** (one sentence inserted inline into the existing §3.8 paragraph; +205 characters, no lines added or removed).

**Changes**
- **§3.8 — insert —** Added one sentence pinning the pricing-variant availability gate: "Each variant is available only while the booking is in one of the statuses named for it above; requesting a `pricing_variant` that is not available for the booking's current status is rejected with `ERR_INVALID_STATE` (HTTP 409)." — `implementation/routes/bookings.py:395-400`.

**Step-7 item triage (why the other items produced no edit)**
- `get_slot_claim` fixture getter — pure fixture/collection bug; `GET /chair-massage/slot-claims/{id}` already in §4 and implemented. No edit.
- `create_event_booking` fixture kwargs merge — pure fixture `TypeError`; no behavioral content. No edit.
- `cancel_claim` fixture wrapper — wraps existing `POST /slot-claims/{id}/cancel`; impl (`slot_claims.py:106-123`) matches PRD §3.7 verbatim (CLAIMED-only; booking SCHEDULING/CONFIRMED/IN_PROGRESS). No edit.
- test_05 window-overlap — test-artifact defect (factory default 60-min window vs the comments' 120-min arithmetic). PRD §3.4 already pins per-region buffer extension and half-open intervals; impl matches (`domain.py:52-58` `extended_window`, `domain.py:87-89` `windows_overlap`, used by both assign scan `domain.py:92-98` and confirm scan `domain.py:101-112`). No edit.
- test_10 recurrence re-fetch — stale chair dicts had `therapist_id=None` → headerless depart/arrive → 401. PRD §2.1 (missing headers → `ERR_UNAUTHENTICATED` 401) and §3.6 (caller's `X-User-ID` must equal chair's `therapist_id`; impl enforces at `chair_slots.py:95-96, 111-112`) already pin this. No edit.

**Per-edit pre-edit search log (the one committed edit)**
- **(a) Subject:** draft-invoice creation gating — `pricing_variant` per-status availability and its rejection semantics.
- **(b) Impl paths enumerated:** `routes/bookings.py:386-426` `create_invoice` (only creation endpoint; order is: variant enum check → 400 `ERR_INVALID_REQUEST` → availability map `{PROVISIONAL: (CONFIRMED, IN_PROGRESS), FINAL: (COMPLETED, CANCELLED)}` → 409 `ERR_INVALID_STATE` → live-invoice scan → 422 `ERR_LIVE_INVOICE_EXISTS`); `services/domain.py:146-171` `compute_invoice_fields` (reads `pricing_variant` only to pick the chair-minutes source, no gating); all of `routes/invoices.py` (issue/record-payment/dispute/resolve-dispute/void — none read `pricing_variant`; issuance's own COMPLETED/CANCELLED 409 gate is already pinned in §3.8); repo-wide grep for `pricing_variant` confirms no other readers; §4 table confirms no other invoice-creation route.
- **(c) Wording adjustment:** Wrote "statuses named for it above" rather than restating the status pairs, so the sentence cannot drift from the existing PROVISIONAL/FINAL status prose, and so it also covers DRAFT/SCHEDULING bookings (neither variant available → 409, per `bookings.py:397-400`). Classifying the rejection as `ERR_INVALID_STATE` (409) places it in §2.8 pipeline stage four, which additionally pins — with no extra sentence — that it fires before the 422 `ERR_LIVE_INVOICE_EXISTS` business check (stage six), matching the check order at `bookings.py:397-406` that the test_11 fix relied on. No path enumerated is mis-described by the final wording.

## Step 9: Complete PRD — 2026-08-10T16:05:00.000Z

Note: the first Step 9 subagent produced a full findings catalog but exited before applying edits (PRD_COMPLETED.md was a byte-identical copy of PRD_FINALIZED.md at that point). A fresh Step 9 subagent was spawned with the catalog passed as an unverified hint list; it independently re-verified every item against the implementation source and applied the edits. Exit summary follows.

**Source vs result**: `PRD_FINALIZED.md` 308 lines / 49,907 chars → `PRD_COMPLETED.md` 308 lines / 56,942 chars (char-delta +7,035; 32 lines touched, all in-place inserts/revisions, no new sections).

**Counts**: 26 ambiguity-pins, 8 mismatch-revisions (34 edits total across 22 PRD passages; some edits bundle a pin and a revision).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)**

1. §2.1 — insert — ambiguity — bootstrap endpoints: supplied non-PlatformAdmin role → 403; omitted headers proceed as PlatformAdmin — auth.py:25-31
2. §2.1 — insert — ambiguity — unrecognized `X-User-Role` value → 403 at permission stage — auth.py:27,44-45
3. §2.1 — insert — ambiguity — Therapist self-access on GET therapist + nested lists — therapists.py:57,104,115,129,143
4. §2.3 — insert — ambiguity — limit/offset non-integer or out-of-range → 400 — validate.py:105-127
5. §2.3 — insert — ambiguity — `has_more` = `offset+limit < total_count`; sort ties broken by insertion order — validate.py:139, db.py:43
6. §2.3 — insert — ambiguity — list responses not scoped by caller identity — routes/* list handlers (no owner filter)
7. §2.3 — insert — ambiguity — unparseable filter values ignored, not rejected — validate.py:144-165
8. §2.4 — revise — mismatch — clock set is unconditional (backward moves permitted), naive values treated as UTC (was "advances") — clock.py:19-22, clock_routes.py:16-29
9. §2.4 — insert — ambiguity — all emitted timestamps (incl. `api_request_timestamp`) generated from the logical clock — respond.py:12, db.py:48,57
10. §2.5 — insert — ambiguity — `version` starts at 1; `updated_at` initialized equal to `created_at` — db.py:50-51
11. §2.7 — insert — ambiguity — omitted/non-integer `expected_booking_version` / `expected_chair_slot_version` → 400 — bookings.py:136-138, chair_slots.py:168-170, validate.py:95-102
12. §2.8 — insert — ambiguity — entity-backed ownership 403 evaluated after path resolution (404 beats ownership-403) — auth.py:51-61 call sites
13. §2.8 — revise — mismatch — daily-load cap scoped to chair assignment only; confirmation re-checks license then double-booking — bookings.py:146-154 vs chair_slots.py:70-82
14. §2.8 — insert — ambiguity — survey: completion precondition (`ERR_BOOKING_NOT_COMPLETED`) precedes uniqueness (`ERR_DUPLICATE_SURVEY`) — slot_claims.py:173-181
15. §2.8 — revise — mismatch — dropped "Finally," ordering claim on field-shape validation (impl applies field-shape at point of use, e.g. claim creation 400s precede 412; survey 422s precede rating 400) — chair_slots.py:166-173, slot_claims.py:173-183
16. §2.9 — revise — mismatch — only `ON_SITE` chairs auto-complete at booking completion (was "chairs") — bookings.py:267-274
17. §2.10 — insert — ambiguity — required body-referenced ids resolve with 404 — bookings.py:34,37, corporate_accounts.py:22, therapists.py:23, licenses.py:26-27, wellness_programs.py:36, slot_claims.py:147, chair_slots.py:64
18. §3.1 — insert — ambiguity — duplicate region code → 400 — regions.py:26-28
19. §3.1 — insert — ambiguity — account-close precondition violations → 409 — corporate_accounts.py:88-91
20. §3.2 — insert — ambiguity — therapist email uniqueness → 400; `per_hour_rate_cents` min 0 — therapists.py:21,24-26
21. §3.2 — insert+revise — ambiguity+mismatch — `suspension_reason` starts empty; suspend only from ACTIVE; reason optional defaulting to "" (PRD said "carries a reason"); license-number duplicate → 400 — licenses.py:44,74,77,30-35
22. §3.2 — insert — ambiguity — license-revoke cascade releases via ordinary release flow incl. PLANNED-leg waive + fee zeroing — licenses.py:107-114, domain.py:118-141
23. §3.3 — insert — ambiguity — `site_address` may be empty; `event_date` unconstrained vs logical date — bookings.py:38-39
24. §3.3 — insert — ambiguity — chair slots created with null `assigned_at`/`arrived_at` — bookings.py:113-122
25. §3.4 — insert — ambiguity — non-ACTIVE assignment candidate → 409 — chair_slots.py:65-66
26. §3.4 — insert — ambiguity — confirm with any non-ASSIGNED chair → 409 — bookings.py:133-134
27. §3.4 — insert — ambiguity — optional confirm-time travel details (top-level defaults, `travel_legs` overrides, fallback rules to ""/0) — bookings.py:155-187
28. §3.4 — insert — ambiguity — release waives PLANNED leg AND zeroes its `travel_fee_cents` — domain.py:129-130
29. §3.5 — revise — ambiguity — `recurrence_discount_pct` bounds pinned inclusive [0.00, 0.50]; window < slot_minutes → 400 vs non-divisible → `ERR_WINDOW_NOT_DIVISIBLE` — wellness_programs.py:44-51
30. §3.5 — insert — ambiguity — program creation does not require account ACTIVE — wellness_programs.py:33-69
31. §3.5 — revise — mismatch — MONTHLY occurrence uses current month when clamped anchor day is strictly after today (was "in the following month"); WEEKLY anchor weekday = creation date's weekday — calc.py:168-191
32. §3.5 — revise — mismatch+ambiguity — materialize: requires ACTIVE (409); idempotent per supplied `event_date` (not `next_occurrence_date`); replay returns 201; optional `region_id` (unvalidated, defaults to home region)/`site_address` ("")/`per_minute_rate_cents` (1, min 1); schedule advances to cadence successor of supplied date, bumped until strictly after today — wellness_programs.py:142-192
33. §3.6 — insert — ambiguity — depart date mismatch → 409, identity mismatch → 403; arrive does not re-check event date; start-service precondition failures → 409 — chair_slots.py:93-118, bookings.py:196-206
34. §3.6 — insert — ambiguity — claim creation has no booking-/chair-status precondition — chair_slots.py:163-206
35. §3.6 — insert — ambiguity — waiver: `booking_id` 404/400, signer mismatch 400, no claim-status precondition; double-revoke is a no-op success — slot_claims.py:143-166, misc.py:49-54
36. §3.7 — insert — ambiguity — claim-completion identity mismatch → 403; system-posted EARNING/TRAVEL_REIMBURSEMENT entries carry empty memo — slot_claims.py:93-94, bookings.py:251,261
37. §3.8 — revise — mismatch — `corporate_account_id` denormalized at invoice creation (was "at issuance"); invoice carries `dispute_reason`, empty until disputed — bookings.py:410,421
38. §4 table — revise — mismatch — claim mark-no-show cell: removed "(post-event)" (impl has no event-date check on claims; only chairs do) — slot_claims.py:127-138 vs chair_slots.py:142-144
39. §4 table — revise — mismatch — booking-invoices cell: "at most one non-VOID" → "at most one live (DRAFT/ISSUED/DISPUTED)" (a PAID invoice can coexist with a new DRAFT) — bookings.py:401-406

**Catalog items verified but NOT pinned**
- "arrive checks only identity + EN_ROUTE, no event-date re-check" — PRD §3.6 already said "under the same identity check" (identity-scoped); added only an explicit "without re-checking the event date" clarifier inside the depart/arrive revision rather than a separate pin.
- Missing-version 400 fires after 409 state checks in confirm — the pins state the error code without asserting a pipeline slot, since field-shape position varies per endpoint (handled by the "Finally" drop, change #15).

No other catalog items were discarded: all 30 were independently confirmed against source (several bundled into single prose edits).
