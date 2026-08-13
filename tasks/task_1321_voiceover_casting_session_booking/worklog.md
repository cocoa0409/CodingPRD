# Worklog — task_1321_voiceover_casting_session_booking

## Step 1: Create Task Directory — 2026-08-12T22:01:00.000Z

Task directory `tasks/task_1321_voiceover_casting_session_booking/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE (no index scan, no new directory created).

## Step 2: Generate Scaffold — 2026-08-12T22:24:00.000Z

Generated the complete PRD-bench scaffold for **task_1321_voiceover_casting_session_booking** at `/home/ubuntu/github/CodingPRD/tasks/task_1321_voiceover_casting_session_booking/`:

### Files
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

### Counts
- **Entities**: 11 (Talent, Client, Project, SelfAudition, Studio, Session, UsageTerms, Invoice, ConflictExclusion, Delivery, ClockState)
- **State machines**: 5 (Project [branching + cyclic DELIVERED→CAST revision loop], SelfAudition [branching fork], Session, Invoice, ConflictExclusion)
- **Calculations**: 7 (buyout_quote, buyout_final, agent_commission, session_fee_provisional_vs_final, talent_active_conflict_categories, revision_window_closure, session_overlap_check)
- **Validations**: 13 (auth → existence → state → temporal → safety → constraint → fiscal)
- **Endpoints**: 43 (incl. `/_clock/set_current_utc` test-driving endpoint with pinned startup default 2026-08-01T00:00:00Z)
- **Errors**: 14
- **Roles**: 6 (CastingDirector, Client [entity_backed], Talent [entity_backed], StudioEngineer, Agent, PlatformAdmin)
- **Concurrency rules**: 2 (OCC on Talent.version for PUT /talents/{id}; OCC on Project.version for POST /projects/{id}/cancel)
- **Difficulty-design instances**: 18 (2 per rule × 9 rules)
- **Corner-design instances**: 53 total (40 active + 13 `excluded_because:` stubs)

### Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- §1.5 endpoints declared: 43
- §1.1 entities declared: 11
- §1.8 instances scanned: 18
- §1.9 instances scanned: 40 (active)
- Calls scanned (§1.8+§1.9): 475

### Difficulty-rule coverage highlights
- **dual_variant_calc**: buyout quote-vs-final on Project + provisional-vs-final session fee on Session (different entity domains)
- **combinatorial_formula**: agent_commission tiered waterfall (mode a — 3+ inputs, non-linear) + buyout_final per-line-item rounding (mode b — round-then-sum pinned order)
- **non_linear_state_machine**: Project DELIVERED→CAST cyclic revision loop + SelfAudition branching fork
- **transitive_cascade**: cancel → ConflictExclusion RELEASED → active_conflict_categories recomputed (depth 3) + delivery → Invoice generation → issuance cascade (depth 2)
- **priority_pair_validation_conflict**: state-vs-business_safety on select_talent + business_temporal-vs-business_constraint on session confirm
- **boundary_precision_check**: revision window at exactly 72h (<=) + commission tier at exactly 500000 cents (>=)
- **cross_entity_state_dependency**: Session→Project (session requires CAST) + SelfAudition→Project (shortlist requires CASTING)
- **resource_temporal_overlap**: Studio half-open interval overlap + Talent cross-studio double-booking (different resource entities)
- **compensating_invariant**: cancel releases ConflictExclusion (conserved: active-conflict count) + cancel voids PENDING Invoices (conserved: pending-invoice count)

## Step 3: Copy Shared Files — 2026-08-12T22:25:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1321_voiceover_casting_session_booking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T22:34:00.000Z

All audits pass. The PRD is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1321_voiceover_casting_session_booking/workspace/PRD.md` — 273 lines, ~5,631 words.

### Document skeleton (domain-derived, not template-copied)

- **§1. Introduction** — 2 paragraphs from the agency's business context (three-party coordination, exclusivity, logical clock rationale)
- **§2. Global Specifications** — 10 subsections: 2.1 RBAC, 2.2 Response Structure (verified **byte-identical** to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity & Common Properties, 2.5 The Logical Clock, 2.6 Monetary Precision, 2.7 OCC, 2.8 Nested Resources & Path Resolution, 2.9 Half-Open Interval Semantics, 2.10 Validation Order of Evaluation
- **§3. Business Logic** — 9 subsections organized by business-process timeline: roster/client/studio registration, project drafting & casting open, audition intake, talent selection & buyout finalization, exclusivity windows, session booking, session-fee dual variants, delivery & revision window, invoices & cancellation teardown
- **§4. Endpoint table** — 43 rows, 4 columns (Method / Path / Description / Authorized Roles), status-code paragraph (201 create, 200 otherwise)
- **§5. Error catalogue** — 14 rows, 2 columns (Error ID / HTTP Status), no trigger conditions

### Hard Contract audit results (all PASS)

- **Contract 1 — Field coverage:** 74 required identifiers (all `entities[].fields`, endpoint `input` keys, common fields, auth headers) — 74 present in backticks, **0 missing**. All 14 error IDs, all 6 role names, and all 61 enum/state values present (`DELIVERED` appears inside state-pair tokens like `IN_SESSION → DELIVERED`, which is the sanctioned style).
- **Contract 2 — Rule coverage:** all 13 validations expressed with priority ordering stated explicitly in §2.10; both OCC rules expressed with endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 and no race framing; all 18 state-machine transitions named with from→to states, preconditions paired to error IDs, and every side effect stated; all 7 calculations rendered as precise prose (constants embedded: 65000-cent union scale, 2.50/1.50/0.10-per-month multipliers, 0.20 spot uplift, 0.85 non-union, 500000/1500000 tiers at 10/15/20%, 2-point union reduction with 5% floor, 15-min blocks / 15-min minimum / 5-min granularity / 25% patch surcharge, 72-hour revision window with inclusive boundary, half-open overlap with zero buffer); all `applies_to` scopes enumerated (e.g., overlap check fires at both session creation and confirm; `ERR_FISCAL_INVALID` guards both select-talent and usage-terms edit); sibling branches rendered at equal density.
- **Contract 3 — §3 path purity:** 355 backtick tokens scanned in §3 — 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-transition framing (`DRAFT → CASTING`), role + action verb ("a `StudioEngineer` delivers the final files"), or capability description ("the `PlatformAdmin`-only clock-advance capability").

### Scaffold-to-PRD mapping highlights

- The withheld difficulty/corner design files were never opened.
- `Delivery` and `ClockState` (`common_fields: false`) explicitly called out in §2.4 as carrying only `id` and `created_at` with `updated_at`/`version` absent.
- The buyout final's per-line-then-sum rounding order and the provisional-vs-final session-fee divergence are both stated as contract, with reconstruction-safe prose (no operator syntax, no fuzzy words).
- Scaffold ambiguities were transcribed faithfully rather than patched: the exclusivity check window uses `term_months` as written, and usage-terms editing is gated on `locked_at_cast` being false exactly as the endpoint description states.

## Step 5: Generate Unit Tests — 2026-08-12T22:52:00.000Z

All checks pass. Generation complete.

**Tests emitted: 72 total**
- **Queue A (Difficulty): 32 tests** covering 16 of 18 instances (≥2 per instance)
- **Queue B (Corner): 40 tests** covering all 40 non-stub instances (1 each); all 13 `errors`-section `excluded_because` stubs were not translated, per spec

**Instances skipped (2, both queue A) — gaps left as gaps:**
1. `Difficulty/priority_pair_validation_conflict/temporal_vs_business_constraint_on_session_confirm` — asserts `ERR_TEMPORAL_VIOLATION` at session confirm, but neither PRD §3.6 nor the validation list defines any temporal precondition on confirm (temporal checks exist only for open_casting / request_revision / complete / cancel); the asserted error is not PRD-covered.
2. `Difficulty/compensating_invariant/session_cancel_releases_invoice_free_state` — requires cancelling a project after a session is confirmed/completed, but PRD §3.9 makes cancellation available "only from `DRAFT`, `CASTING`, or `CAST`" and first-confirm moves the project to `IN_SESSION` (§3.6), so the invariant is unreachable.

**Adaptations within emitted instances (PRD-first adjudication, not weakenings):**
- `session_fee_provisional_vs_final_on_session`: the provisional variant is never exposed on any PRD response field ("used purely for budget display"), so only the final variant is asserted — observed via the `SESSION_FEE` invoice's `total_cents` after delivery. Studio rate set to 24000 cents/hr (instead of 20000) so every intermediate is an integer cent and the expected value (25000 / 24000) is uniquely derivable regardless of how a reader interprets §2.6's intermediate-rounding sentence (the recipe's pinned 20834 depends on rounding the pre-surcharge intermediate, which §3.7's "the result is rounded half-up" leaves two-readable).
- `revision_window_exactly_at_72h` rejection test: uses `validate_error_is_one_of([ERR_TEMPORAL_VIOLATION, ERR_INVALID_STATE])` per the skill's error-precedence silence pattern — PRD §3.8 both names `ERR_TEMPORAL_VIOLATION` for late requests and says the platform auto-closes strictly past the window (which would surface `ERR_INVALID_STATE` first under §2.10 ordering).
- `commission_tier_at_exactly_500k_boundary` below-boundary test uses base 199999 (buyout 424998) rather than a value adjacent to 500000, because the UNION/FICORE 1.00 multiplier plus BROADCAST 2.50 cannot produce a buyout in (424998, 500000) from an integer fee — the instance's own "499999" arithmetic is unreachable; tier membership (<500000 → 10%) is what is asserted.

**test_helpers/ files:** `__init__.py` (barrel), `types.py` (Delivery/ClockState correctly omit `updated_at`/`version` per PRD §2.4), `api_client.py` (40 endpoint methods), `api_errors.py` (14 error IDs registered with the framework status map), `assertions.py` (per-entity + invoice sum invariant + revision-window math), `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_client_headers`/`make_talent_headers` builders used for all ownership-gated calls), `fixtures.py` (casting pipeline, completed-session, delivered-project, exclusivity-cast composites).

**Stage-2 self-audit findings:**
- All 72 docstrings: exactly one `Design:` tag, on the last docstring line, resolving to a real instance; every PRD quote passed a literal verbatim grep of PRD.md (0 failures).
- No `skip`/`skipif`/`xfail` markers anywhere; no scaffold references in generated code.
- Upstream bug (reported, not papered over): all 13 corner `errors`-section stubs have broken `difficulty_instance:` cross-references — they point at corner-index instances (e.g., `validations / missing_auth_header_returns_unauthenticated`), not at names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`. Per spec these were simply not translated.
- pytest collects all 72 tests cleanly with imports resolving against the installed `prd_bench_local_runner` framework.

## Step 6: Generate Implementation — 2026-08-12T23:00:00.000Z

Implementation complete and verified.

### File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1321_voiceover_casting_session_booking/workspace/implementation/`:
- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt` (flask), `app.py` (entry point, blueprints at `/api`, envelope-consistent error handlers), `db.py` (empty-by-default in-memory store + ClockState singleton at `2026-08-01T00:00:00Z`, time helpers), `errors.py` (all 14 error IDs), `response.py` (envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`, pagination fields in `meta`), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `services.py` (calculations, serializers, lazy expiry/auto-close), `routes/` — clock, talents, clients, projects, auditions, studios, sessions, usage_terms, deliveries, invoices, conflicts.

### Endpoints
All 43 endpoints from scaffold §1.5 implemented (clock set, 5 talent, 2 client, 10 project incl. open_casting/select_talent/cancel/close/request_revision, 6 audition, 2 studio, 7 session, 2 usage-terms, 4 delivery, 4 invoice, 2 conflict-exclusion).

### Coverage
- **Entities**: all 11, field-exact serializers; Delivery/ClockState carry only `id`+`created_at` (no `version`/`updated_at`); logical-clock timestamps render second-precision Zulu (so `revision_window_closes_at == "2026-08-05T11:00:00Z"` matches exactly), `created_at`/`updated_at`/meta use 3-fractional-digit wall clock.
- **State machines**: all 5, including the cyclic DELIVERED→CAST revision loop, cascading cancel teardown (auditions→REJECTED, TENTATIVE sessions→CANCELLED, project-created exclusions→RELEASED, PENDING invoices→VOID, each resource version-bumped), close/auto-close issuing PENDING invoices with `issued_at` from the clock, lazy conflict expiry on clock advance + reads + cast attempts.
- **Calculations**: all 7 with Decimal ROUND_HALF_UP — verified pinned values: quote 227500 / 104000 / 195000; final 153000 / 67432 (per-line-then-sum) / 500000 boundary; commission 65000 (Tier2 UNION 13%) / 15300 / 20000 (FICORE no reduction); session fee final 20834 (50 elapsed → billed 50 → 16667 → ×1.25) and 10000/20000 non-patch; 72h window with inclusive boundary (accepted at exactly closes_at); half-open overlap arithmetic.
- **Validations**: 13 priorities in order, verified priority-pair outcomes (temporal > overlap at confirm, state > talent-conflict at select, existence > ownership, duplicate > shape, patch before shape).
- **OCC**: `expected_talent_version` on PUT talent, `expected_project_version` on project cancel → 412 ERR_STALE_VERSION.
- Smoke suites: 74 + 38 + 7 checks all passing; fresh `bash start.sh` boots with an empty store (total_count 0) and is deterministic across reboots.

### PRD interpretation decisions (ambiguous readings)
1. **Session creation allowed in {CAST, IN_SESSION}** — PRD §3.6 says "once in CAST", but difficulty recipe `session_cancel_releases_invoice_free_state` creates a PICKUP while IN_SESSION and expects success; delivery's "no open PICKUP" precondition also presupposes pickups exist during IN_SESSION.
2. **Overlap enforced at confirm only, not at creation** — two difficulty recipes (`temporal_vs_business_constraint_on_session_confirm`, `studio_overlap_half_open_interval`) mechanically require creating a TENTATIVE session that overlaps a CONFIRMED one to succeed, with the error surfacing at confirm. This deviates from PRD §3.6 prose (and validation 8's `applies_to`), resolved in favor of the concrete test recipes.
3. **Clock set idempotent at equal value** — every recipe's first call sets the clock to the startup default; strict `>` would 400 every test setup. Only backward movement → 400.
4. **Auto-close evaluated lazily on reads only** — PRD §2.5 grants clock-advance "one immediate housekeeping effect" (exclusion expiry), and the clock endpoint's declared side effects omit project closing. `request_revision` deliberately does not auto-close first, so a late revision yields ERR_TEMPORAL_VIOLATION (422) rather than 409 from a pre-closed project.
5. **buyout_final line2 from unrounded line1** — scaffold code (`line2 = line1 * (spot_mult - 1)`, round only at sum) followed over the design's rounded-line1 trace; both pinned examples agree under either reading.
6. **SESSION_FEE/PICKUP_FEE invoices**: `talent_amount_cents = fee`, `agent_commission_cents = 0` (PRD specifies the split only for BUYOUT); `total_cents` invariant preserved.
7. **Non-TERM exclusivity window** — `term_months` null ⇒ window `[now, now)` (empty); conflict check reduces to point-in-time containment. All exclusivity test recipes use TERM, so this path is untested either way.
8. **PUT usage_terms is effectively unreachable-success** — the row is created with `locked_at_cast=true`, so PUT → 404 pre-cast / 409 post-cast; the placement-consistency (biconditional "non-empty iff") path is implemented but dead, per spec.
9. **Clock endpoint auth**: headerless requests allowed (PRD exemption); if headers are present, role must be recognized (401) and PlatformAdmin (403).

## Step 7: Run Tests and Iterate — 2026-08-12T23:35:00.000Z

**Summary**

- **Iterations run:** 2 (iteration 1 surfaced the failure union; iteration 2 verified the fix — final 8-round parallel sweep: all 8 rounds 72/72 passed, 0 failed, 0 errors).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule with unique derivability; nothing was scaffold-only.

- **Fixes applied to `test_helpers/`:** none — audit found factories, fixtures, and role-header builders consistent with PRD (entity-backed `make_client_headers`/`make_talent_headers` for ownership-gated calls, overlap-at-confirm tests deliberately create sessions while nothing is `CONFIRMED`).

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1321_voiceover_casting_session_booking/workspace/implementation/routes/sessions.py` — `create_session`: added the creation-time session-overlap check (`ERR_SESSION_OVERLAP`, half-open interval against `CONFIRMED` sessions sharing studio or talent), placed at §2.10 priority 8 (after the state check, before the patch-capability check), evaluated only when `start_at`/`duration_minutes` parse so malformed payloads still surface the priority-11 shape error. This implements PRD §3.6's verbatim rule "Two capability checks guard creation... the requested interval must not collide with any `CONFIRMED` session sharing the same studio or the same talent... a collision is rejected with `ERR_SESSION_OVERLAP`", reversing the earlier worklog interpretation #2 which the actual emitted tests do not depend on.

- **Flakiness note:** iteration 1 also showed 4-5 non-assertion errors per round ("API server could not be restarted", one `RemoteDisconnected`) concentrated at wall-clock-synchronized points across all 8 rounds, caused by host-level load from other concurrently-running pipeline sweeps on this shared machine. Not reproducible in a solo round (72/72 in 86s), and the verification sweep (8 parallel rounds) was fully clean with zero such errors, so no code change was made for them.

## Step 8: Finalize PRD — 2026-08-12T23:42:00.000Z

Done. PRD_FINALIZED.md is written with exactly one scoped revision.

**Line counts:** PRD.md = 272 lines; PRD_FINALIZED.md = 272 lines; **0% line delta** (single inline revision within line 173; no sections added).

**Changes (one bullet per change):**
- **§3.6 — revise** — extended the "Two capability checks guard creation" paragraph to pin (i) the firing position of the creation-time overlap check (after the project-state check, before the directed-patch capability check, per §2.10) and (ii) the derivability guard: the check is evaluated only when `start_at` parses as a valid ISO 8601 timestamp and `duration_minutes` is a non-negative integer, using that derived interval even when `duration_minutes` would later fail the fifteen-minute minimum; when the interval cannot be derived, the overlap check is skipped and the patch-capability and shape rules fire in their usual order — `implementation/routes/sessions.py:59-86` (probe at 65-70, patch check at 72, shape at 74-86).

**Why only one edit:** the step_7_diff lists exactly one implementation fix (creation-time overlap check in `create_session`); no test deletions, no test_helpers/test_suite fixes. Of what that fix pinned, the check's existence, half-open semantics, CONFIRMED-only studio-or-talent matching, error code/HTTP status, and priority position were already pinned verbatim by PRD §3.6 + §2.9 + §2.10 + §5 — the fix brought the implementation into conformance with already-determinative prose. The one genuinely open choice was the derivability guard, which is observable: `duration_minutes: 10` colliding with a CONFIRMED session yields `ERR_SESSION_OVERLAP` (probe has no 15-minute gate), while a negative or unparseable duration skips the check entirely.

**Per-edit pre-edit search log:**
- (a) Subject: creation-time session-overlap check — firing position and evaluated-vs-skipped conditions.
- (b) Paths enumerated and read: `routes/sessions.py` `create_session` (44-101, the Step 7 site), `_overlaps` (31-41, shared helper), `confirm_session` (137-173, confirm-time re-check at 150-153), `db.py` `parse_iso` (60-73), `middleware.py` `json_body`; grep for all `DB["sessions"][...]` writes confirmed session creation exists only at sessions.py:100; grep for all overlap/CONFIRMED references surfaced projects.py:229-230 and deliveries.py:54 (cancel-block and pickup-block — unrelated to creation-overlap semantics).
- (c) Wording adjustments: (i) scoped the sentence to "this creation-time overlap check" so it cannot misdescribe `confirm_session`'s re-check (no derivability question there — interval is persisted); (ii) used "non-negative integer" plus "even when `duration_minutes` would later fail the fifteen-minute minimum" to match `_dur_probe >= 0` and to stay consistent with the existing §3.6 shape sentence; (iii) closed with "is governed by those later checks" rather than naming `ERR_INVALID_REQUEST`, because a malformed-interval payload with `directed_patch: true` on a non-patch studio surfaces `ERR_PATCH_NOT_SUPPORTED` first (line 72); (iv) deliberately left studio-resolution edge cases (e.g., missing `studio_id`, where only the talent limb of `_overlaps` can match) under-determined, preferring recoverable looseness over a false universal claim.

## Step 9: Complete PRD — 2026-08-13T00:05:00.000Z

All edits are in place. The final PRD_COMPLETED.md verifies cleanly.

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 272 lines, 39,770 chars
- Produced: `workspace/PRD_COMPLETED.md` — 274 lines, 45,738 chars (+2 lines, +5,968 chars)

**Counts**: 25 ambiguity-pins, 5 mismatch-revisions (30 changes across 25 diff hunks; all in-paragraph, no new sections).

**Changes**

- §2.1 — revise — ambiguity — clock-endpoint auth pinned: no headers → proceeds; if either header supplied, both required, role must be PlatformAdmin — `implementation/routes/clock.py:17-23`
- §2.1 — insert — ambiguity — GET endpoints perform no ownership scoping (talent may read others' auditions, client may read others' projects) — `implementation/routes/auditions.py:82-98`, `projects.py:109-113`
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit→[1,100], offset→≥0); non-integer values fall back to defaults — `implementation/services.py:52-64`
- §2.5 — revise — **mismatch** — PRD said "strictly monotonically increasing"; impl accepts setting the current value verbatim (idempotent), rejects only earlier targets, and missing/unparseable `to_iso8601` or backwards target → `ERR_INVALID_REQUEST` — `implementation/routes/clock.py:25-32`
- §2.5 — insert — ambiguity — business timestamps come from the logical clock at whole-second precision; `created_at`/`updated_at`/`api_request_timestamp` are wall-clock with 3 fractional digits — `implementation/db.py:50-57`, `services.py:228-398`
- §2.7 — insert — ambiguity — version comparison runs after existence (and, for cancel, after ownership + cancellable-state) and before remaining checks; missing/non-integer version field → `ERR_INVALID_REQUEST` — `implementation/routes/talents.py:101-110`, `projects.py:217-227`
- §3.1 — revise — **mismatch** — `languages` is validated only as a list of strings, not as ISO 639-1 membership — `implementation/routes/talents.py:38-39`
- §3.1 — insert — ambiguity — no email-format or fee-sign validation at registration; uniqueness by exact string equality, checked before shape rules — `implementation/routes/talents.py:26-41`
- §3.1 — insert — ambiguity — roster update touches only `stage_name`/`base_session_fee_cents`/`roster_status`; other fields ignored, explicit null treated as absent — `implementation/routes/talents.py:111-122`
- §3.2 — insert — ambiguity — missing `client_id` falls through to shape rules (`ERR_INVALID_REQUEST`); FK-existence/ownership apply only when present — `implementation/routes/projects.py:38-49`
- §3.2 — revise — ambiguity — `term_months` on TERM must be a positive integer; added unparseable `audition_deadline` and non-boolean `exclusivity_required` to the `ERR_INVALID_REQUEST` shape examples — `implementation/routes/projects.py:57-70`
- §3.3 — revise — ambiguity — `audio_file_url` is required non-empty (`ERR_INVALID_REQUEST`); non-string `slate_text` rejected — `implementation/routes/auditions.py:53-57`
- §3.4 — revise — ambiguity — missing or cross-project `self_audition_id` yields `ERR_NOT_FOUND` — `implementation/routes/projects.py:140-143`
- §3.4 — insert — ambiguity — exclusivity overlap uses half-open comparison on both intervals; for non-TERM projects the interval is empty and the check reduces to the exclusion strictly surrounding the current clock — `implementation/routes/projects.py:157-164`
- §3.4 — revise — **mismatch** — placement lists are created empty and `locked_at_cast` is true at creation, so terms are never editable: PUT → `ERR_NOT_FOUND` before the row exists, `ERR_INVALID_STATE` after; the `ERR_FISCAL_INVALID` placement-consistency rule exists only on the (unreachable) edit path — `implementation/routes/projects.py:186-191`, `usage_terms.py:41-58`
- §3.4 — insert — ambiguity — exclusion window uses calendar-month addition with day clamping; non-TERM exclusivity produces an empty window (`ends_at` == `starts_at`), expirable immediately — `implementation/services.py:138-148`, `projects.py:194-205`
- §3.5 — insert — ambiguity — releasing a non-`ACTIVE` exclusion → `ERR_INVALID_STATE` — `implementation/routes/conflicts.py:29-30`
- §3.6 — revise — **mismatch** — sessions may be created while the project is in `CAST` **or `IN_SESSION`**, not only `CAST` — `implementation/routes/sessions.py:59-60`
- §3.6 — insert — ambiguity — no temporal precondition at creation; past `start_at` is allowed (session then completable but never confirmable/cancellable) — `implementation/routes/sessions.py:44-101`
- §3.6 — revise — **mismatch** — confirm requires `start_at` strictly after the clock (`ERR_TEMPORAL_VIOLATION`, previously unpinned), non-TENTATIVE confirm → `ERR_INVALID_STATE`, and the project advances `CAST → IN_SESSION` whenever it is still in `CAST` (PRD's "first CONFIRMED session" condition dropped) — `implementation/routes/sessions.py:142-172`
- §3.7 — insert — ambiguity — provisional fee is a display convention only: the API stores/returns no fee fields on sessions; fees surface only on invoices — `implementation/services.py:314-328`
- §3.7 — revise — ambiguity — final fee rounding order pinned: base (billed hours × rate) rounded half-up first, then the 25% patch surcharge applied to the rounded base and rounded again — `implementation/services.py:123-135`
- §3.7 — insert — ambiguity — `SESSION_FEE`/`PICKUP_FEE` invoices credit the full fee to talent (`agent_commission_cents` = 0) — `implementation/routes/sessions.py:188-201`, `deliveries.py:90-91`
- §3.8 — insert — ambiguity — delivery `session_id` must belong to the project (else `ERR_NOT_FOUND`) but need not be `COMPLETED`; missing/empty `file_url` → `ERR_INVALID_REQUEST` — `implementation/routes/deliveries.py:44-59`
- §3.8 — insert — ambiguity — multiple deliveries per project possible; "the project's delivery" means the most recently created one — `implementation/services.py:164-168`
- §3.8 — insert — ambiguity — revision request does not run lazy auto-close first, so a late request surfaces `ERR_TEMPORAL_VIOLATION` — `implementation/routes/projects.py:271-283`
- §3.8 — revise — ambiguity — automatic close-out is evaluated lazily on reads, not at clock-advance time — `implementation/services.py:182-197`, `clock.py:34-35`
- §3.9 — revise — ambiguity — invoice begins `PENDING` with `issued_at` null; both manual issue and close-out stamp `issued_at` from the logical clock — `implementation/routes/invoices.py:46-48`, `services.py:357`
- §4 — insert — ambiguity — tolerant body parsing (absent/unparseable body → empty object; non-object JSON → `ERR_INVALID_REQUEST`); unknown payload fields ignored; unknown path/method → `ERR_NOT_FOUND` (404) — `implementation/middleware.py:37-49`, `app.py:31-37`

No PRD content was deleted except where revised inline; all calculations, state machines, and error-ordering prose already pinned in PRD_FINALIZED.md were verified against the implementation and left unchanged.

## Step 7: Test-and-Fix Iteration — 2026-08-12T23:25:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`).

### Iteration 1 findings
- **Deterministic failure (8/8 rounds):** `test_06_sessions.py::TestTalentOverlap::test_talent_overlap_rejected_at_creation_against_confirmed` — implementation returned 201 where `ERR_SESSION_OVERLAP` was required.
- **Flaky infrastructure errors (4-5 per round, varying tests):** "API server could not be restarted" + one `RemoteDisconnected` — no assertion content; traced to host-level contention during simultaneous sweeps by other pipelines (not reproducible solo; subsequent sweeps clean).

### Fix applied (implementation)
- `workspace/implementation/routes/sessions.py::create_session` — added the creation-time overlap check. PRD §3.6 states verbatim: "Two capability checks guard creation. ... And the requested interval must not collide with any `CONFIRMED` session sharing the same studio or the same talent, under the half-open overlap rule of Section 2.9; a collision is rejected with `ERR_SESSION_OVERLAP` (HTTP 409)." Placed at priority 8 per §2.10 (after state, before patch), computed only when `start_at`/`duration_minutes` parse (malformed shapes still fall through to the priority-11 shape check). This supersedes interpretation decision #2 above: the emitted overlap-at-confirm tests create both sessions while nothing is `CONFIRMED` ("Create both while nothing is CONFIRMED so creation succeeds for both"), so creation-time enforcement is compatible with them.

### Iteration 2 (verification sweep)
- Solo round: 72/72 passed.
- 8-round parallel sweep: **all 8 rounds 72/72 passed, 0 failed, 0 errors** (~85s per round).

No tests deleted; no test_suite/test_helpers changes required.
