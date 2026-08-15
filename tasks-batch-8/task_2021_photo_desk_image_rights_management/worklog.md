# Worklog — task_2021_photo_desk_image_rights_management

## Step 1: Create Task Directory — 2026-08-15T07:33:00.000Z

Pre-created by the pipeline invocation: tasks/task_2021_photo_desk_image_rights_management/ and workspace/ already existed; orchestrator skipped index computation per instructions.

## Step 2: Generate Scaffold — 2026-08-15T08:17:49.112Z

Scaffold generation complete for task 2021 (Photo Desk & Image Rights Management). All three artifacts written and the mechanical lint passes clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_2021_photo_desk_image_rights_management/SCAFFOLD.yaml` — §1.0–§1.7 (fixed envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles). No difficulty/corner keys.
- `/home/ubuntu/github/CodingPRD/tasks/task_2021_photo_desk_image_rights_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8).
- `/home/ubuntu/github/CodingPRD/tasks/task_2021_photo_desk_image_rights_management/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9).

**Counts**
- Entities: 9 (Photographer, StoryRequest, Assignment, Image, License, ReleaseRecord, UsageRun, InfringementClaim, PaymentRun)
- State machine blocks: 9 across 8 entities (Image carries two parallel dimensions: editorial `status` × `restriction_status`); cyclic shapes on Assignment (revision loop), InfringementClaim (offer/counter negotiation), Image.restriction (NONE⇄RESTRICTED)
- Calculations: 6 (license_fee_quote, photographer_payout, settlement_split, rights_reversion_date, usage_ordinal_and_tier, assignment_kill_fee)
- Endpoints: 50 (incl. `POST /_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z startup default)
- Error codes: 32
- Difficulty instances: 19 (all 9 rules ≥2; combinatorial_formula has 3, one per mode a/b/c)
- Corner instances: 54 (43 active + 11 `excluded_because` stubs, all resolving to real §1.8 names)

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (421 calls scanned, all conform to §1.5; all FKs reverse-reachable). Instance names unique across both design files; forbidden concurrency vocabulary scan clean; every formula-derived assert pre-computed to a literal (e.g. reuse fee 7200 vs first-use 12000; royalty 153/line → 459 vs sum-then-round 458; tier crossing 3429→4001 at the 10th use; clawback 30000 → accrued 10000; kill fee 25000).

**Notable design decisions**
- Archetype: compliance/audit primary, temporal-windowing secondary; flat peer topology (FK-linked, no URL nesting); segregation_of_duties role model — a claim's resolver must differ from its `intaken_by_user_id`.
- Sourcing decision modeled as a one-shot `POST /story-requests/{id}/decide` fork: COMMISSION spawns an Assignment, WIRE_STOCK links a cleared image — covering the assignment-vs-wire decision as a branching state machine.
- Two OCC true-races (create-with-supersede): license creation on Image.version, payment-run creation on Photographer.version; both guarded by `expected_*_version` with ERR_STALE_VERSION/412.
- Interval semantics deliberately contrasted for Rule 8: exclusivity overlap uses half-open windows (adjacency allowed) while photographer double-booking uses closed windows + 1-day travel buffer (adjacency rejected); license usage window is closed at `valid_to` while embargo is exclusive-before/`>=`-allowed at the instant.
- Lazy system transitions for License EXPIRED / ReleaseRecord EXPIRED / rights reversion, all driven by the declared logical clock, keeping time rules deterministic.
- Compensating invariants pinned as formulas: story `committed_cents == Σ ACTIVE linked fees` (activate/revoke pair) and photographer `paid_out_cents == Σ PAID totals` (pay/void pair).

## Step 3: Copy Shared Files — 2026-08-15T08:18:30.000Z

Copied ./INSTRUCTION.md → tasks/task_2021_photo_desk_image_rights_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T08:24:01.689Z

# PRD Generation Complete

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_2021_photo_desk_image_rights_management/workspace/PRD.md`
**Line count:** 354

## Sections written

- **§1 Introduction** — 2 paragraphs, product-manager framing (editorial urgency vs rights discipline, finance's two payout models)
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (with role identity semantics for all 6 roles), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock & Time Semantics (lazy EXPIRED derivation), 2.5 Common Resource Properties (with `UsageRun` `common_fields: false` called out), 2.6 Monetary Values & Rounding, 2.7 OCC (both rules), 2.8 Validation Priority Ordering (all 25 priorities enumerated), 2.9 Cascading Side Effects
- **§3 Business Logic & Workflows** — 9 subsections organized by lifecycle: 3.1 Photographer Roster, 3.2 Story Requests & Sourcing Decision, 3.3 Images (Ingest/Metadata/Embargo/Archive), 3.4 Assignments (Shoot/Submit/Accept/Kill Fees), 3.5 Licensing (Quote/Exclusivity/Budget/Supersession), 3.6 Releases, 3.7 Publication & Rights Reversion, 3.8 Infringement Claims, 3.9 Payment
- **§4 Endpoint Definitions** — 50 endpoints in a 4-column table
- **§5 Error Code Catalogue** — 32 errors in a 2-column table

## Coverage counts

| Category | Required | Present | Missing |
|---|---|---|---|
| Entity fields (`entities[].fields[].name`) | 82 | 82 | 0 |
| Endpoint request inputs (`endpoints[].input`) | 65 | 65 | 0 |
| Common fields (`id`/`created_at`/`updated_at`/`version`) | 4 | 4 | 0 |
| Role names | 6 | 6 | 0 |
| State enum values (all state machines incl. `Image.restriction_status`) | all | all | 0 |
| Error IDs | 32 | 32 | 0 |

**State machines:** all 9 scaffolds (Photographer, StoryRequest, Assignment, Image, Image.restriction_status, License, ReleaseRecord, InfringementClaim, PaymentRun) fully rendered — every transition's from/to states, preconditions (paired with error IDs), and side effects.

**Calculations:** all 6 (`license_fee_quote`, `photographer_payout`, `settlement_split`, `rights_reversion_date`, `usage_ordinal_and_tier`, `assignment_kill_fee`) rendered as precise prose — pinned evaluation order preserved (scope→territory→exclusivity→reuse-discount; per-line round-then-sum; clawback-first-then-cascade-then-debit), constants embedded (`KILL_FEE_PCT` 0.5 → "one half"; `PHOTOGRAPHER_LIABILITY_PCT` 0.30 → "30 percent"; `TIER_THRESHOLD` 10; `TIER_MULTIPLIER_HIGH` 1.5; full scope/territory/channel multiplier tables).

**Endpoints:** all 50 from scaffold listed in §4 with authorized roles.

**Errors:** all 32 IDs present in §2/§3 prose triggers and §5 table.

## Hard contract reports

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body: 65 required, 65 present, 0 missing
- endpoints[].query_params: 0 separately declared (filters carried in input lists), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed in prose (§2.8 ordered list + per-endpoint relative order restated in §3.5 activation gates, §3.7 usage-run gate)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_image_version/expected_photographer_version + ERR_STALE_VERSION/412 all named; no race-winner framing)
- state_machines[].transitions: 41 checked, 41 fully expressed (from/to/preconditions/side-effects all in §3)
- calculations[]: 6 checked, 6 fully expressed with constants and pinned rounding
- validations[] conditions: 25 checked, 25 matchable to error_id in prose
- endpoints[].side_effects / applies_to: all expressed (cascades in §3.2 cancel, §3.4 accept/kill-fee, §3.5 supersede/activate/revoke, §3.7 first-publish, §3.8 UPHELD/DISMISSED resolution outcomes, §3.9 pay/void; applies_to sets honored)
- entities[].fields[] structured content: 82 checked, 82 reconstructible (defaults for rights_reversion_months=24, keywords=[], has_identifiable_people/has_private_property=false, territory=DOMESTIC, exclusive=false, min/max_image_count 1/10, status defaults; UsageRun common_fields=false stated in §2.5)
- sibling-branch symmetry: COMMISSION vs WIRE_STOCK branches, GUARANTEE vs ROYALTY payout variants, UPHELD vs DISMISSED resolution outcomes, FIRST_USE vs REUSE pricing variants — all rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 500
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notable doc decisions

1. **§2.4 Logical Clock** — promoted to a top-level cross-cutting subsection (rather than buried in §3) because it drives four independent lazy-derivation rules (license expiry, release expiry, embargo check, rights reversion) and the `_clock/set_current_utc` default `2026-08-01T00:00:00Z` is a contract-level constant.
2. **§2.8 Validation Priority Ordering** — enumerated all 25 priorities as an ordered list so the §3 narratives can reference "the relative order given in §2.8" without re-listing 25 items at every gate; §3.5 and §3.7 then restate the operative sub-order for their specific endpoints.
3. **§3 subsection count = 9**, organized by entity lifecycle (roster → story → image → assignment → license → release → usage → claim → payment), matching the domain's natural pipeline rather than a fixed 7-subsection template.
4. **UsageRun `common_fields: false`** explicitly stated in §2.5 ("immutable ledger entry carrying `id` and `created_at` only; no `updated_at`, no `version`").
5. **Constants embedded in prose** rather than as a table — "one half" for `KILL_FEE_PCT`, "30 percent" for `PHOTOGRAPHER_LIABILITY_PCT`, "ten or higher" for the tier threshold, "1.5" tier multiplier — while numeric multipliers for scope/territory/channel are listed inline as "1.0 for PRINT, 1.2 for DIGITAL, ..." so the formula is reconstructible step-for-step.
6. **No pseudocode** — all formulas translated to prose ("the photographer's day_rate_cents multiplied by the assignment's day_count, multiplied by one half, rounded half-up to integer cents"), preserving operand order and boundary inclusivity ("at or before", "strictly before", "inclusive at both ends", "half-open — including valid_from, excluding valid_to").

## Step 6: Generate Implementation — 2026-08-15T08:45:55.830Z

The implementation is complete and verified. Here is the summary:

---

## Summary

### Files Written (14 source files)

| File | Purpose |
|------|---------|
| `workspace/implementation/start.sh` | Launcher script |
| `workspace/implementation/requirements.txt` | Flask dependency |
| `workspace/implementation/app.py` | Entry point, app factory, error handlers, blueprint registration |
| `workspace/implementation/db.py` | In-memory data store (9 dicts), logical clock, UUID generation, ISO parsing |
| `workspace/implementation/errors.py` | ApiError exception class + 31 error ID constants |
| `workspace/implementation/response.py` | Envelope helpers: `meta`/`response_type`/`data` for success, error, and paginated list responses |
| `workspace/implementation/middleware.py` | Auth header extraction (X-User-ID, X-User-Role), role validation, RBAC, Photographer ownership |
| `workspace/implementation/serializers.py` | Entity-to-dict serializers for all 9 entity types, with lazy expiry derivation for License and ReleaseRecord |
| `workspace/implementation/services/calculations.py` | All 6 calculation rules + lazy expiry processors |
| `workspace/implementation/routes/photographers.py` | 5 endpoints (create, read, suspend, reactivate, payment-runs CRUD) |
| `workspace/implementation/routes/story_requests.py` | 4 endpoints (create, read, decide with COMMISSION/WIRE_STOCK branches, cancel with cascades) |
| `workspace/implementation/routes/assignments.py` | 7 endpoints (list, read, submit image, list images, submit, accept, request-revision, cancel) |
| `workspace/implementation/routes/images.py` | 10 endpoints (ingest, search, read, clear, archive, embargo, reuse-check, usage-runs CRUD, licenses CRUD) |
| `workspace/implementation/routes/licenses.py` | 5 endpoints (list, read, activate, revoke, usage-runs list) |
| `workspace/implementation/routes/releases.py` | 3 endpoints (create, list, revoke) |
| `workspace/implementation/routes/claims.py` | 8 endpoints (intake, list, read, review, offer, counter, escalate, resolve) |
| `workspace/implementation/routes/payment_runs.py` | 4 endpoints (read, approve, pay, void) |
| `workspace/implementation/routes/clock.py` | 1 endpoint (set logical clock) |

### Endpoints Implemented: 50

All 50 endpoints from the scaffold endpoint table are implemented, matching the PRD endpoint table exactly.

### State Machines Implemented (7)

1. **Photographer**: ACTIVE <-> SUSPENDED (suspend/reactivate)
2. **StoryRequest**: OPEN -> DECIDED -> FULFILLED; OPEN/DECIDED -> CANCELLED (with cascade: assignment cancel + license revoke + budget release)
3. **Assignment**: COMMISSIONED -> IN_PROGRESS -> SUBMITTED -> ACCEPTED/REVISION_REQUESTED/CANCELLED; REVISION_REQUESTED -> IN_PROGRESS (revision cycle); kill fee on cancel from SUBMITTED/REVISION_REQUESTED
4. **Image** (editorial): INGESTED -> CLEARED -> PUBLISHED -> ARCHIVED; CLEARED -> ARCHIVED
5. **Image.restriction_status**: NONE <-> RESTRICTED (latched by claim intake/UPHELD; lifted by DISMISSED when no other open claims)
6. **License**: DRAFT -> ACTIVE -> REVOKED/EXPIRED; DRAFT -> REVOKED; lazy EXPIRED derivation with budget release; supersession sets superseded_by_id
7. **ReleaseRecord**: ACTIVE -> REVOKED/EXPIRED; lazy EXPIRED derivation
8. **InfringementClaim**: INTAKE -> UNDER_REVIEW -> SETTLEMENT_OFFERED <-> COUNTERED -> ESCALATED; resolve from any non-terminal state to RESOLVED (UPHELD) or DISMISSED
9. **PaymentRun**: DRAFT -> APPROVED -> PAID -> VOIDED; DRAFT/APPROVED -> VOIDED; PAID->VOIDED debits paid_out_cents

### Calculations Implemented (6)

1. **license_fee_quote**: scope multiplier -> territory multiplier -> exclusivity multiplier -> REUSE discount (0.6x if times_used>0), round_half_up once at end. Constants: SCOPE(1.0/1.2/0.8/1.5), TERRITORY(1.0/1.3/1.6), EXCLUSIVE(2.0), REUSE_DISCOUNT(40%).
2. **photographer_payout**: guarantee (day_rate * day_count per ACCEPTED assignment + per_image_fee per cleared image) vs royalty (sum of per-line royalty_cents in period), minus clawbacks, floored at 0. Method from photographer_type.
3. **settlement_split**: 30% of settlement for ASSIGNMENT images (round_half_up), 0 for WIRE/STOCK.
4. **rights_reversion_date**: first_published_at + photographer.rights_reversion_months calendar months.
5. **usage_ordinal_and_tier**: ordinal = times_used+1; tier 1.5 at ordinal>=10; royalty = rate * channel_multiplier * tier, round_half_up per line. WIRE/STOCK images get 0.
6. **assignment_kill_fee**: round_half_up(day_rate * day_count * 0.5) on cancel from SUBMITTED/REVISION_REQUESTED.

All monetary calculations use `decimal.Decimal` with `ROUND_HALF_UP`, never float.

### start.sh Behavior

- **PORT handling**: `app.py` reads `os.environ.get("PORT", "10000")` and binds to that port.
- **Bind address**: `0.0.0.0` (all interfaces).
- **Foreground exec**: `exec python3 app.py` -- the shell script replaces itself with the Python process, so signals (SIGTERM from the test harness) propagate directly to Flask.
- **Dependency install guard**: `if ! python3 -c "import flask"` -- skips `pip install` when Flask is already importable, avoiding contention during per-test-server reboots.
- **Fresh state per boot**: `init_store()` in `create_app()` clears all dicts and resets the logical clock to 2026-08-01T00:00:00Z. No seeding, no persistence.

## Step 5: Generate Unit Tests — 2026-08-15T08:57:35.576Z

Generation complete. Summary:

## Files written

**test_helpers/** (9 modules, all under `tasks/task_2021_photo_desk_image_rights_management/test_helpers/`):
- `types.py` — 6 role + 14 status/type enums; 10 entity TypedDicts (UsageRun correctly modeled common_fields-false: no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (43 methods incl. the logical-clock endpoint)
- `api_errors.py` — all 32 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `parse_instant` (compares instants, not timestamp strings — PRD pins instants, not serialization format)
- `factories.py`, `constants.py` (all calculation multipliers/thresholds), `test_users.py` (`TEST_USERS` + mandatory `make_photographer_headers` for the entity-backed Photographer role + `make_rights_manager_headers` for SoD user pairs)
- `fixtures.py` — composite setup chain: `commission_assignment`, `create_accepted_assignment`, `ingest_cleared_wire_image`, `create_draft_license`/`create_active_license` (OCC version re-read built in), `record_usage_run`, `intake_claim`/`move_claim_under_review`, `create_payment_run` (OCC re-read), `set_logical_clock`
- `__init__.py` — barrel export

**test_suite/** — `conftest.py` + 8 test files: `test_01_photographers_and_stories.py` (6), `test_02_assignment_lifecycle.py` (9), `test_03_images_archive_search.py` (11), `test_04_licensing.py` (17), `test_05_usage_runs.py` (15), `test_06_infringement_claims.py (11), test_07_payment_runs.py` (7), `test_08_access_control.py` (4).

## Test counts
- **80 tests total: 38 queue A + 42 queue B.** All 80 collect under pytest; every docstring carries a verbatim PRD quote (0 grep failures) + exactly one `Design:` tag resolving to a real instance; no skip/xfail markers.
- Queue A: all 19 difficulty instances × 2 tests each. Queue B: 42 of 43 non-stub instances × 1 test; all 11 `excluded_because:` stubs left untranslated with cross-references verified resolving.

## Instances skipped
- **Corner/entities/photographer_email_must_be_unique** — PRD §3.1 states "Each photographer's `email` is unique across the roster" but never names the rejection error/status for a duplicate; a faithful PRD-only reader could enforce with `ERR_INVALID_REQUEST`/400 or not enforce at all. Fails unique derivability; gap left as a gap.

## Notable generation decisions
1. **`photographer_double_booking_buffer_closed` (queue A) partially translated with a documented drop.** Its recipe asserts a 2026-08-14 shoot succeeds against an existing 08-10..08-12 assignment. PRD §3.2 pads *both* windows ("the commissioned shoot window padded... must not intersect the *similarly padded* window of any other assignment... touching the buffer day counts as a conflict"): new padded [08-13,08-15] ∩ existing padded [08-09,08-13] = {08-13} → conflict under the PRD's plain reading, contradicting the recipe's "2026-08-14 clears the buffered window". I emitted two tests asserting only the uniquely-derivable conflicts (trailing buffer day 08-13, leading buffer day 08-09, plus a genuinely-free 08-15 case that is disjoint under *both* padding readings). The "08-14 free" leg is a design-index/PRD bug left as a documented gap — not weakened into the suite.
2. **`reuse_check_computed_read_blockers_and_quote`** — asserts `eligible` (false→true), `requires_model_release`/`requires_property_release`, `fee_quote_cents` 12000, `pricing_variant` FIRST_USE, and that `blocking_reasons` is a list. The instance's expected membership of specific `ERR_*` strings in `blocking_reasons` was dropped: PRD §3.7 never pins the list's element format, so two readers could ship different-but-faithful encodings.
3. **Timestamp assertions compare parsed instants** (`parse_instant`), not raw strings — PRD pins instants, while `Z` vs `+00:00`/fractional-digit formatting is an open design space.
4. Priority-pair instances (rule 5) were kept because PRD §2.8's numbered list plus the explicit tie-resolution sentence ("on a usage-run creation, embargo... are reported in that relative order after the editorial gate"; "the release gate surfaces before the exclusivity conflict, which surfaces before the budget check") provide verbatim coverage; each pair got one dual-failure test plus one isolated single-failure test.

## Step 7: Run Tests and Iterate — 2026-08-15T09:09:38.614Z

All 8 rounds of the final confirmation sweep passed 80/80 — 640/640 executions green against the final tree state. The task is complete.

## Summary

**Iterations run:** 3 sweeps total. Sweep 1 surfaced the failure union (6 tests failing deterministically in all 8 rounds; the apparently "flaky" extra FAILED lines in the interleaved console output were stdout-garbling artifacts of 8 concurrent pytest processes — the per-round results.json files were authoritative and identical). Sweep 2 verified the fixes (640/640). Sweep 3 was a clean final confirmation of the finished tree (640/640).

**Tests deleted:** none — every failing test traced to a verbatim PRD rule with unique derivability; all were STEP 2 test bugs.

**Fixes applied to `test_suite/`** (4 edits):
- `test_suite/test_04_licensing.py` — added the missing `get_image_version` import; `test_license_create_stale_image_version_rejected` used it without importing it (NameError).
- `test_suite/test_05_usage_runs.py::test_embargo_fires_when_editorial_gate_passes` — `published_at` was "2026-08-20", *after* the setup's 2026-08-05 embargo, so per PRD §3.7 ("must not be strictly before the image's `embargo_until`") publication is allowed and the implementation correctly succeeded; changed to "2026-08-03", strictly before the embargo and inside the license window, so ERR_EMBARGO_ACTIVE fires as the test intends.
- `test_05_usage_runs.py` (`test_per_line_royalty_rounded_half_up_at_creation`, `test_royalty_total_is_sum_of_rounded_lines`) — added `channel="SOCIAL"` to the usage-run calls; the setup creates a SOCIAL license and PRD §3.7 requires "the run's `channel` must equal the license's `usage_scope`", so the implementation's ERR_SCOPE_NOT_LICENSED rejection was correct and the payload was the bug.
- `test_suite/test_07_payment_runs.py::_setup_freelance_with_assignment_and_two_social_runs` — same SOCIAL channel fix on both `record_usage_run` calls; repaired `test_both_amounts_always_computed_on_payment_run` and `test_freelance_run_selects_royalty_method`.

**Fixes applied to `test_helpers/`:** none — the factories' DIGITAL default is a valid default; the failing tests simply failed to override it.

**Fixes applied to `implementation/`** (2 proactive PRD-fidelity corrections found during review; neither was required by a failing test, both trace to verbatim PRD prose, both behavior-neutral for the existing suite):
- `workspace/implementation/routes/story_requests.py::_decide_commission` — reordered the double-booking check before the suspended-photographer check to match PRD §2.8's explicit priority order (11 before 12).
- `workspace/implementation/routes/photographers.py::create_payment_run` — moved the OCC `ERR_STALE_VERSION` check before the DRAFT auto-void side effect, per PRD §2.7 ("a writer holding a stale view of the parent resource would revoke or void state it never observed") and §2.9's atomicity rule ("the operation either applies all of its cascades or none").

## Step 8: Finalize PRD — 2026-08-15T09:15:09.926Z

PRD_FINALIZED.md produced at `workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta:** PRD.md = 354 lines; PRD_FINALIZED.md = 354 lines; 0% delta (byte-identical copy).

**Changes:** none. Every `<step_7_diff>` item traced to a verbatim PRD rule with unique derivability, so the minimal correct patch is the identity:

- The 4 `test_suite/` fixes were pure STEP 2 test bugs against already-pinned PRD rules: the missing `get_image_version` import (NameError, no behavioral content); the embargo test payload (PRD §3.7 already pins "strictly before" embargo semantics — impl `routes/images.py:459-462` matches verbatim); and the three `channel="SOCIAL"` additions (PRD §3.7 already pins "the run's `channel` must equal the license's `usage_scope`" — impl `routes/images.py:481-482` matches verbatim).
- The 2 `implementation/` fixes converged the impl **to** the PRD; at both sites the current implementation now behaves exactly as the PRD already uniquely determines, so no PRD wording change is warranted (per "Where PRD already determines behavior, keep prose verbatim").

**Per-edit pre-edit search log** (two candidate edits evaluated, both rejected):

1. **Candidate: pin double-booked-before-suspended order (§2.8/§3.2).**
   - (a) Subject: relative order of `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` vs `ERR_PHOTOGRAPHER_SUSPENDED` on the COMMISSION decide branch.
   - (b) Enumerated paths: grep for both error ids across `implementation/` — the only raise sites are `routes/story_requests.py:165` (double-booked) and `routes/story_requests.py:170` (suspended), in that order; no parallel endpoint raises either. Read `_decide_commission` in full (`routes/story_requests.py:111-197`).
   - (c) Edit rejected: PRD §2.8's numbered list (item 11 before item 12) plus its preamble ("Evaluated in order", "these priorities resolve ties") already uniquely determines the order; §3.2 prose lists both rules without asserting check order, so nothing conflicts. No wording committed.

2. **Candidate: pin OCC-check-before-auto-void order (§2.7/§2.9/§3.9).**
   - (a) Subject: ordering of `ERR_STALE_VERSION` relative to the DRAFT auto-void cascade on payment-run creation.
   - (b) Enumerated paths: grep for `ERR_STALE_VERSION` and `VOIDED` — raise sites at `routes/photographers.py:204` (payment-run OCC, now before the auto-void at lines 206-219) and the parallel `routes/images.py:319` (license OCC, before the supersession cascade at lines 328-346); the only other `VOIDED` write is the explicit void endpoint `routes/payment_runs.py:86-90` (unrelated). Also read `services/calculations.py` (payout/lazy-expiry paths that advance `photographer.version`, feeding §2.7's rationale).
   - (c) Edit rejected: PRD §2.7 bullet 2 (stale → reject, rationale "would revoke or void state it never observed"), §2.9 ("applies all of its cascades or none"), §2.8 item 25, and §3.9's auto-void sentence jointly pin the current behavior at both OCC sites. No wording committed.

With zero edits, the NO-NEW-MISMATCH rule is trivially satisfied; Step 9 can treat PRD_FINALIZED.md as the alignment base.

## Step 9: Complete PRD — 2026-08-15T09:27:12.597Z

PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md (354 lines / 44,050 chars) → PRD_COMPLETED.md (360 lines / 49,258 chars), char-delta +5,208. PRD.md and PRD_FINALIZED.md were byte-identical.

**Counts:** 15 ambiguity-pins, 9 mismatch-revisions (24 edited passages; the §2.8 passage and the §3.2 decide passage each bundle related fixes).

Changes, one per bullet:

- §2.1 — insert — ambiguity — pinned `include_archived` parsing: only the string `true` (any case) counts; `1`/`yes`/other values treated as false — implementation/routes/images.py:85
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped, not rejected; non-integer values → `ERR_INVALID_REQUEST`; `total_count` = filtered count pre-pagination; `has_more` ⟺ `offset + limit < total_count` — implementation/routes/photographers.py:134-140 (pattern repeated in all list endpoints), implementation/response.py:38
- §2.4 — insert — ambiguity — clock accepts any parseable instant (no monotonicity check); lazy expiry is latched on first observation (persisted status, `updated_at` refresh, `version` increment), so rewinding the clock does not resurrect expired records — implementation/routes/clock.py:26, implementation/services/calculations.py:195-240
- §2.7 — revise — mismatch — both OCC bullets: impl enforces `expected_image_version` / `expected_photographer_version` only when the field is supplied; omission proceeds with no check (PRD said "requires … else rejected") — implementation/routes/images.py:318, implementation/routes/photographers.py:203
- §2.8 item 4 — revise — mismatch — added exception: the optional `story_request_id` on license creation is never resolved to an existing story — implementation/routes/images.py:302 (no lookup)
- §2.8 closing paragraph — revise — mismatch — three endpoint-specific orderings: (a) `Photographer` ownership is checked against the path id before record load on photographer-rooted paths, but after assignment load (and after caption/credit-line shape validation on image submission) on assignment-scoped paths; (b) decide applies the `OPEN` check immediately after the story itself resolves, ahead of branch shape/FK validation; (c) claim resolve checks state and SoD before validating `settlement_amount_cents` — implementation/routes/photographers.py:79,127, implementation/routes/assignments.py:78-99, implementation/routes/story_requests.py:96-145, implementation/routes/claims.py:219-237
- §3.1 — revise — mismatch — email uniqueness is not enforced (PRD claimed unique across roster) — implementation/routes/photographers.py:29-51 (no check)
- §3.1 — insert — ambiguity — explicit null `rights_reversion_months` also falls back to 24 — implementation/routes/photographers.py:48-51
- §3.2 — revise — mismatch — story `slug` uniqueness is not enforced (PRD claimed unique) — implementation/routes/story_requests.py:37-38 (no check)
- §3.2 — insert — ambiguity — `needed_by` must parse as a valid ISO 8601 instant, else `ERR_INVALID_REQUEST` — implementation/routes/story_requests.py:41-42
- §3.2 — revise — ambiguity — double-booking buffer computed as exact-timestamp ±24h (not calendar-date truncation), closed-interval comparison — implementation/routes/story_requests.py:149-164
- §3.2 — revise — mismatch — `decision_notes` is accepted but not stored (serializer has no such field) — implementation/serializers.py:32-47
- §3.2 — revise — mismatch — story-cancel cascade releases budget only for licenses that were `ACTIVE`; `DRAFT` releases nothing and already-lapsed licenses are left `EXPIRED` (PRD said `committed_cents` decreases by each revoked license's fee) — implementation/routes/story_requests.py:250-261
- §3.3 — insert — ambiguity — clear gate: whitespace-only `credit_line` counts as empty — implementation/routes/images.py:158
- §3.3 — insert — ambiguity — `q` is a case-insensitive substring match against caption and space-joined keywords — implementation/routes/images.py:110-115
- §3.4 — revise — ambiguity — acceptance cascade applies the per-image fee accrual as a single ledger addition with the photographer's `version` incrementing once for the whole cascade (PRD read as per-image incrementing) — implementation/routes/assignments.py:230-233
- §3.4 — revise — mismatch — revision `feedback` note is accepted but not stored — implementation/routes/assignments.py:238-254 (no field read/stored)
- §3.4 — revise — mismatch — cancellation `reason` is accepted but not stored (PRD said "may be recorded") — implementation/routes/assignments.py:257-286 (no field read/stored)
- §3.5 — insert — ambiguity — `valid_to` earlier than `valid_from` rejected with `ERR_INVALID_REQUEST` — implementation/routes/images.py:293-294
- §3.5 — revise — mismatch — license-create OCC sentence aligned to enforce-only-when-supplied semantics — implementation/routes/images.py:318
- §3.5 — insert — mismatch — dangling `story_request_id` on a license is stored as-is: budget gate inert at activation, nothing accrues or releases — implementation/routes/licenses.py:148-153,162-167
- §3.7 — insert — ambiguity — zero-valued royalty line leaves the photographer record (and its `version`) untouched — implementation/routes/images.py:513-518
- §3.7 — insert — ambiguity — first-run effects (PUBLISHED transition, `first_published_at`, reversion projection) fire only from `CLEARED`; a run on an `ARCHIVED` image changes neither status nor stamps, though royalty and `times_used` still apply — implementation/routes/images.py:499-507
- §3.7 — insert — ambiguity — reuse-check quote assumes non-exclusive `DOMESTIC`, absent/invalid `channel` quotes as `PRINT`; pinned the four `blocking_reasons` tokens and their check order — implementation/routes/images.py:221-263
- §3.8 — insert — ambiguity — `DISMISSED` resolution also stamps `resolved_by_user_id` — implementation/routes/claims.py:281-285
- §3.9 — revise — mismatch — payment-run OCC sentence aligned to enforce-only-when-supplied semantics — implementation/routes/photographers.py:203
- §5 — insert — ambiguity — fallback errors outside the catalogue: `ERR_NOT_FOUND` (404 for undefined paths, 405 for unsupported methods) and `ERR_INTERNAL` (500), both in the standard envelope — implementation/app.py:46-56

Notable deliberate non-changes: unvalidated `embargo_until` string formats on ingest/submission (write paths that matter — the PUT — do validate; the gate skips unparseable values), and `min_image_count`/`max_image_count` cross-validation absence were left silent as too deep in the weeds relative to any plausible divergent reading.
