# Worklog — task_0513_online_teletherapy

## Step 1: Create Task Directory — 2026-06-26T19:35:47.000Z

Created `tasks/task_0513_online_teletherapy/workspace/`. Task directory pre-allocated per orchestrator instructions; index 0513 used as given (no re-scan). Project root: `/Users/uni/Desktop/吉/project/custom_prd_bench`.

## Step 2: Generate Scaffold — 2026-06-26T19:51:00.000Z

Everything validates. All nine difficulty rules have exactly 2 instances each (18 total), file split is honored (neither design key appears in SCAFFOLD.yaml), and the lint is clean. The scaffold is complete and self-consistent.

Generated all three scaffold artifacts for **task_0513_online_teletherapy** at **Expert** difficulty:
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Complexity profile:** primary `workflow_orchestration` + secondary `compliance_audit`; layers = cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, scheduled_actions, optimistic_concurrency; topology `hybrid`; state shape `cyclic`; role model `peer_roles`; consistency `immediate`.

**Entities (14):** Client, Therapist, TherapistLicense, IntakeQuestionnaire, Match, Subscription, BillingCycle, SessionCredit, LiveSession, MessageThread, Message, CrisisEscalation, FinancialAidApplication, Superbill.

**State machines (9):** Client (PENDING_INTAKE→AWAITING_MATCH→ACTIVE↔SUSPENDED→CLOSED), Therapist (ONBOARDING→ACCEPTING↔FULL→INACTIVE), Match (cyclic: PROPOSED→ACTIVE→SWITCH_REQUESTED→ENDED with successor born ACTIVE), Subscription (cyclic: TRIALING→ACTIVE↔PAUSED, ACTIVE→ACTIVE renewal self-loop, →CANCEL_SCHEDULED→CANCELLED), LiveSession (SCHEDULED→COMPLETED/CANCELLED/NO_SHOW), MessageThread (OPEN↔FROZEN→ARCHIVED), CrisisEscalation (OPEN→ACKNOWLEDGED→RESOLVED), FinancialAidApplication (SUBMITTED→APPROVED/DENIED), Superbill (DRAFT→ISSUED→VOID). Plus 2 concurrency_rules (OCC on Match.version for session scheduling; OCC on Subscription.version for pause).

**Counts:** 5 calculations (financial-aid banding, cycle billing with pinned discount-then-wallet order, pause proration refund, superbill service-value reimbursement, weighted match_score), 19 validations (priority-ordered), 61 endpoints (incl. FK reverse-reachability GETs and a `/_clock/set_current_utc` test-driving endpoint defaulting to 2026-05-01T00:00:00Z), 20 errors, 4 roles (Client/Therapist entity-backed; ClinicalAdmin/BillingAdmin opaque).

**Difficulty design:** 18 instances — exactly 2 per each of the 9 §0.5 rules.
**Corner design:** 36 active instances across entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, and consistency_model (plus `excluded_because` stubs pointing at §1.8 instances).

**Lint:** `python3 scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (453 calls scanned across 18 + 36 instances).

Note: `api_prefix` is `/` (flat root). All formula-derived assertions computed by hand and pinned as literals (match_score=55/45, TIER_2 list 5940 / charged 2546, pause refunds 9900 and 5657, TIER_3 list 3960, reimbursable 9900); two pause→resume→renewal chains had clock advances inserted so the renewal 7-day gate is satisfied. Hard constraint honored — no sibling task directories inspected.

## Step 3: Copy Shared Files — 2026-06-26T19:52:14.000Z

Copied `INSTRUCTION.md` → `tasks/task_0513_online_teletherapy/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T19:58:35.000Z

All checks pass. The PRD is complete and all three hard contracts are satisfied.

**File written:** `workspace/PRD.md` (275 lines).

**Document structure:** §1 Introduction → §2 Global Specifications (11 subsections: RBAC, response envelope, pagination, common properties, OCC + logical clock, cascades, nested retrieval, money/rounding, enumerations, logical clock, validation ordering) → §3 Business Logic (9 workflow subsections) → §4 Endpoint table (61 rows) → §5 Error table (20 rows). Ends cleanly at §5 with no audit footer.

**Entities documented (15):** Client, Therapist, TherapistLicense, IntakeQuestionnaire, Match, Subscription, BillingCycle, SessionCredit (common_fields:false — id+created_at only), LiveSession, MessageThread, Message (common_fields:false), CrisisEscalation, FinancialAidApplication, Superbill.

**State machines documented (11):** Client, Therapist, Match (reassignment cycle), Subscription, LiveSession, MessageThread, CrisisEscalation, FinancialAidApplication, Superbill — all preconditions paired with error IDs and side-effect cascades.

**Calculations documented (5):** financial_aid_tier_banding (strict-< ceilings), cycle_billing_amount (discount-first/wallet-last, trialing/renewal variants), pause_proration_refund (forward-looking, floor elapsed-days, same-day/late-week variants), superbill_reimbursable_amount (chronological aggregation, floor per-session value on list_amount), match_score (weighted 10/25/2). All constants embedded; all reconstructible.

**OCC documented (2):** expected_match_version on live-session scheduling and expected_subscription_version on pause — both with ERR_STALE_VERSION (412).

**Hard Contract Reports:** Contract 1 (Field-Name Coverage) PASS — 51/51 entity fields, 27/27 endpoint I/O fields. Contract 2 (Rule Coverage) PASS — all validations/OCC/transitions/calculations/conditions expressed, 0 missing, 0 asymmetric. Contract 3 (§3 Path Purity) PASS — 379 tokens scanned, 0 path/method tokens leaked. §2.2 verified byte-for-byte. Withheld design files not opened.

## Step 5: Generate Unit Tests — 2026-06-26T20:24:01.000Z

All 72 test functions carry exactly one `Design:` tag. The test infrastructure is complete and fully validated.

**Test files:** 9 files in `test_suite/` (1 `conftest.py` + 8 `test_*.py`).

**Test functions emitted:** 72 total
- `test_01_billing_and_wallet.py` — billing eval order, pause proration, banding, wallet conservation
- `test_02_matching_and_scoring.py` — match_score, reassignment cycle, caseload bubbling, license routing
- `test_03_cascades_and_safety.py` — finalize-cancel & acute-resolve cascades, pause/resume cycle, crisis suspend
- `test_04_live_sessions_and_credits.py` — overlap/buffer conflicts, credit conservation, OCC, credit expiry
- `test_05_superbills_and_messaging.py` — superbill service-value, thread-freeze gating, messaging, auto-resume
- `test_06_validations_and_boundaries.py` — priority conflicts, boundary precision, single-rule validations
- `test_07_clients_rbac_and_listing.py` — entity defaults, not-found/FK/enum, listing, RBAC
- `test_08_difficulty_depth.py` — the mandatory 2nd-angle test for each of the 18 difficulty instances

**Queue A (Difficulty):** 18 instances, all 18 translated, each with exactly 2 tests (36 tags). 0 skipped.
**Queue B (Corner):** 41 instances total. 36 non-stub instances translated (1 test each). 5 `excluded_because:` stubs correctly NOT translated (all difficulty cross-references verified). 0 non-stub instances skipped.

**Key adjudication note:** Both Rule-5 priority-conflict instances translated. `state_vs_safety` uniquely derivable from §2.11's structural-rung ordering (state check before business rules). `safety_vs_referential` (intake-before-license) uniquely derivable from §2.11's business-rule enumeration ("risk blocks, intake clearance, license coverage").

**test_helpers/ files written (9):** `__init__.py`, `types.py`, `api_client.py` (61 endpoint methods), `api_errors.py` (20 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Validation:** All files parse; SessionCredit/Message modeled `common_fields:false`; all imports/method calls resolve; every cited PRD sentence verbatim-greps against PRD.md; no scaffold leakage; no skip/xfail; every test carries exactly one Design tag.

## Step 6: Generate Implementation — 2026-06-26T20:24:01.000Z

Generated a complete Python + Flask implementation in `workspace/implementation/`.

**File list:** `start.sh` (executable, guards pip on `import flask`, `exec python3 app.py`), `requirements.txt` (Flask 3.0.3), `app.py` (entry, blueprints, error handlers, reads `$PORT`/binds `0.0.0.0`), `clock.py` (logical clock default `2026-05-01T00:00:00Z`), `db.py` (in-memory dicts), `errors.py` (20 error IDs + HTTP statuses), `response.py` (envelope helpers), `middleware.py` (X-User-ID/X-User-Role auth), `serialize.py` (per-entity projection; light entities omit updated_at/version), `validate.py`, `lookup.py` (not-found/ownership/pagination), `services/calc.py` (aid banding, cycle billing Decimal round-half-up, pause proration, match_score), `services/domain.py` (license recompute, caseload bubbling, cascades, clock-advance follow-ons), `routes/` (clients, therapists, matches, live_sessions, threads, subscriptions, resources, crisis, financial_aid, superbills, clock_route).

**Endpoints:** 61 method+path pairs (60 domain + `/_clock/set_current_utc`), matching spec exactly.

**Storage & clock:** Purely in-memory (dicts in `db.py`); no SQLite/disk/seeding. Logical clock starts `2026-05-01T00:00:00Z`, never wall-clock; `set_current_utc` triggers license recompute, PAUSED auto-resume, CANCEL_SCHEDULED auto-finalize (+ client-close cascade), and credit expiry.

**start.sh:** Reads `$PORT` (default 10000), binds `0.0.0.0` foreground via `exec`. Verified boot via `bash start.sh` (~4s).

**Note:** per validation priority table (ERR_CLIENT_RISK_BLOCKED priority 8 < OCC priority 11), live-session scheduling checks risk-block before version check, consistent with PRD §2.11.

HARD CONSTRAINT honored: impl-gen subagent did not read test_suite/ or test_helpers/ (generated purely from INSTRUCTION + SCAFFOLD + PRD).

## Step 7: Run Tests and Iterate (continuation after Bedrock 503) — 2026-06-27T00:00:00.000Z

**Iterations run:** 1 full 8-round parallel sweep to diagnose + 1 to verify (plus initial sweep-command debugging — the runner only honors a working directory when the start command is in `cd <dir> && <cmd>` form, so the start command had to carry the absolute `cd .../implementation && bash start.sh` prefix).

**Final sweep result:** All 8 rounds passed — **71/71** in every round (0 failed, 0 errors). Stable across the full parallel sweep.

**Starting state:** 69/72 stable across 8 rounds, with 3 consistent failures (the prior run's other listed failures already passed). Note: the 3 failures fixed here differ from the original prompt's list because earlier fixes had already landed.

### Tests deleted (1)
- **`test_same_match_closed_adjacency_session_allowed`** (test_04_live_sessions_and_credits.py)
  - Category: **STEP 1b unique-derivability failure / branch-contradiction** (complete PRD reading contradicts the asserted outcome).
  - Behavior asserted: two end-to-start adjacent (0-minute gap) sessions on the **same match** are allowed (HTTP 201), citing only PRD §3.5 guard 2 (overlap: end-to-start touching allowed). But the same §3.5 paragraph states guard 3 verbatim — "the new session must respect a 15-minute buffer against every other non-terminal session belonging to the same therapist across all of that therapist's matches … at least 15 minutes apart". Two same-match sessions always share a therapist, so a 0-minute-gap adjacency unconditionally trips guard 3 → `ERR_THERAPIST_DOUBLE_BOOKED`. The implementation is PRD-correct; the asserted 201 is not uniquely derivable and is in fact forbidden by the full prose, and no fixture can make it allowable. Coverage is preserved: buffer-allowed boundary (≥15 min) by `test_therapist_exact_buffer_gap_allowed`, buffer-rejection by `test_therapist_double_book_within_buffer_rejected`, overlap-rejection by `test_session_overlap_same_match_rejected`. A delete-rationale comment was left in place of the function.

### Fixes applied to test_suite/
- None (other than the deletion above).

### Fixes applied to test_helpers/
- None.

### Fixes applied to implementation/ (timestamp-format consistency)
The two timestamp failures (`test_renewal_charge_succeeds_exactly_at_seven_days`, `test_resume_resets_current_period_start_to_clock`) asserted PRD-derivable **value semantics** (renewal advances `current_period_start` by exactly 7 days → `2026-06-08T00:00:00Z`; resume resets it to the clock → `2026-06-03T00:00:00Z`) but failed only on serialization format: the impl emitted `.000Z` while the entire test suite uses the bare-second-Z form (zero `.000Z`/`.123Z` literals anywhere; the passing `pause_resumes_on == "2026-07-01T00:00:00Z"` confirms the suite's canonical form). PRD line 82 pins the three-fractional-digit form to **only** the audit timestamps `created_at`/`updated_at` (and line 45 `api_request_timestamp`); it is silent on the format of domain instant fields. The impl was also internally inconsistent (`pause_resumes_on` echoed bare-Z, `current_period_start` used `.000Z`). Fix: serialize domain instant fields in second-precision bare-Z, reserving `.000Z` for the PRD-pinned audit timestamps.

- **clock.py** — added `iso_instant(dt)`: ISO 8601 UTC at second precision (no fractional digits), with a docstring scoping it to clock-derived/supplied domain instants. `iso_millis` unchanged (still used for `created_at`/`updated_at`/`submitted_at`).
- **routes/subscriptions.py** — `charge_cycle`: `period_start`, `period_end`, credit `expires_on`, and `current_period_start` now use `iso_instant`; `cancel_sub`: `cancel_effective_on` now uses `iso_instant`. (These fields are never asserted against `.000Z` anywhere and are consumed elsewhere only via format-agnostic `parse_iso`.)
- **services/domain.py** — `resume_subscription`: `current_period_start` now uses `iso_instant` (the resume path that the resume test exercises).

No PRD-required check was weakened, no endpoint/field/side-effect added, and storage remains in-memory only.

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-27T00:00:00.000Z

**Line counts:** PRD.md = 275 lines; PRD_FINALIZED.md = 277 lines. Delta: +2 lines (+0.73%).

### Changes (one bullet per change)

- **§2.4 Common Resource Properties — insert — pinned the serialization format split between audit timestamps (three-fractional-digit `.000Z`) and server-computed domain instants (second-precision bare-Z `…:SSZ`), and clarified that body-supplied instant fields are echoed verbatim** — `implementation/clock.py:21-37` (`iso_millis` vs `iso_instant`), with field-by-field tracing to `routes/subscriptions.py:90-91,100,116,118,208`, `services/domain.py:149`, `routes/clients.py:85`, `response.py:18`.

### Step 7 diff item disposition

1. **Deleted test `test_same_match_closed_adjacency_session_allowed`** — No PRD edit. Confirmed the impl is PRD-correct per the full §3.5 prose (PRD line 154 already states the 15-minute buffer applies to "every other non-terminal session belonging to the same therapist across all of that therapist's matches"; `routes/matches.py:301-311` enforces guard 3 over all the therapist's matches, including same-match). This is a unique-derivability/branch-contradiction deletion that reveals no PRD silence.

2. **Timestamp-format fix** — The genuine PRD silence; pinned as above. PRD line 45 pinned `.000Z` to `api_request_timestamp` and line 82 to `created_at`/`updated_at`, but was silent on the serialization format of server-computed domain instant fields. The impl emits those at second-precision bare-Z.

### Per-edit pre-edit search log

**Edit: §2.4 timestamp-format pin**

(a) **Subject identified:** serialization format of every instant-valued field the implementation emits (audit timestamps, server-computed domain instants, and body-echoed instants).

(b) **Impl paths enumerated and read/grepped** (`grep -rn "iso_millis\|iso_instant"` plus per-field write-site reads):
- `clock.py:21-37` — `iso_millis` (three fractional digits) vs `iso_instant` (second precision, bare-Z); docstring scopes `iso_instant` to clock-derived/operator-supplied domain instants.
- **`iso_millis` (audit) sites:** `db.py:39,53,63` (`created_at`/`updated_at`); `routes/clients.py:85` (`submitted_at`); `response.py:18` (`api_request_timestamp`).
- **`iso_instant` (server-computed domain instant) sites:** `routes/subscriptions.py:90` (`period_start`), `:91` (`period_end`), `:100/:107` (credit `expires_on`), `:116/:118` (`current_period_start`), `:208` (`cancel_effective_on`); `services/domain.py:149` (`current_period_start` on resume).
- **Body-echoed (stored verbatim, NOT re-serialized) sites:** `routes/subscriptions.py:177` (`pause_resumes_on` = `data["resume_on"]`); `routes/therapists.py:82` (license `expires_on` = `data["expires_on"]`); `routes/matches.py:322-323` (session `starts_at`/`ends_at` = `data[...]`); `routes/superbills.py:73-74` (superbill `period_start`/`period_end` = `data[...]`).
- **Auxiliary (test) evidence:** `test_suite/test_06_validations_and_boundaries.py:116` asserts `current_period_start == "2026-06-08T00:00:00Z"` (bare-Z) for a server-computed field; all fixture-supplied instants use bare-Z.

(c) **Wording adjustment made:** The Step 7 diff's framing ("domain instant fields … second-precision bare-Z") would, taken as a universal claim, mis-describe the four body-echoed fields, which the impl stores and echoes verbatim rather than re-serializing. Per the NO-NEW-MISMATCH rule I re-scoped the new sentence into three explicit, mutually exclusive lists — (1) the audit timestamps that keep `.000Z`, (2) the exact set of server-computed domain instants that use bare-Z, and (3) the body-echoed instants that are returned exactly as supplied — so the PRD wording is consistent with every enumerated impl path, not just the Step 7 site. I avoided any blanket "all domain instants serialize as bare-Z" universal, which would have been a false claim against the echoed fields.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-27T00:00:00.000Z

**File metrics**
- `PRD_FINALIZED.md`: 277 lines, 47,530 chars
- `PRD_COMPLETED.md`: 277 lines, 53,422 chars (same line count — all edits are in-paragraph; char delta **+5,892**)

**Change counts:** 19 edits total — **13 ambiguity-pins**, **6 mismatch-revisions**. (Several inserts bundle a few closely-related sub-points within one paragraph touch.)

**Per-change list** (`{section} — {kind} — {type} — {what} — {impl ref}`):

- §2.3 Pagination — insert — ambiguity — sort tie-break by creation sequence; out-of-range/non-integer `limit`/`offset` → `ERR_VALIDATION`; per-endpoint `status`/`state_code`/`client_id`/`therapist_id`/`superseded_by_match_id` list filters; unknown params ignored — lookup.py:45-54; clients.py:56, therapists.py:52-63, matches.py:99-106, live_sessions/clients credit & cycle lists
- §2.4 Common Properties — revise — mismatch — `version` "begins at its initial value" → "begins at 1 on creation" — db.py:46
- §2.11 Validation Ordering — revise — mismatch — out-of-range `severity_score` (and `household_size`/fee/grant/caseload) yields `ERR_INVALID_REQUEST`, not `ERR_VALIDATION`; named the actual `ERR_VALIDATION` sources (pause horizon + pagination) — validate.py:38-41; clients.py:70
- §3.1 Intake — insert — mismatch — `GET /clients/{id}/intake` returns an array-typed envelope, not a bare object; named `ERR_INVALID_STATE` for duplicate / not-PENDING_INTAKE submission — clients.py:104, 73-78
- §3.2 Therapist activate/deactivate — insert — ambiguity — no-VALID-license activation and active-match deactivation (and wrong-state) → `ERR_INVALID_STATE` — therapists.py:110-121, 132-138
- §3.3 Match accept — insert — ambiguity — business-check order (risk → license → therapist availability); therapist-not-ACCEPTING / caseload-full → `ERR_INVALID_STATE` — matches.py:124-133
- §3.3 Fit score — insert — ambiguity — no-intake client scored with empty concerns / severity 0; gate doesn't block — matches.py:52-61
- §3.4 Thread — insert — mismatch — `GET /matches/{id}/thread` returns array envelope (direct `GET /threads/{id}` is an object); `unread_for_therapist` only increments, never decrements — matches.py:249; threads.py:28, 52-54
- §3.4 Reassignment — insert — mismatch — reassign returns `201` with the successor match; added the `AWAITING_MATCH`→`ACTIVE` promotion side effect — matches.py:214, 200-202
- §3.5 Credit reservation — insert — ambiguity — reserves the oldest `AVAILABLE` credit by `created_at` — matches.py:316, 348
- §3.5 Schedule guards — revise — mismatch — risk check precedes the version (OCC) check; explicit guard priority order; non-terminal = `SCHEDULED` — matches.py:289-315
- §3.5 Complete — insert — ambiguity — pre-`starts_at` / non-`RESERVED`-credit completion → `ERR_INVALID_STATE` — live_sessions.py:63-69
- §3.5 Cancel window — revise — ambiguity — within-window = gap to `starts_at` strictly < 24h (includes cancellation at/after start; exactly 24h is outside) — live_sessions.py:88
- §3.5 No-show — insert — ambiguity — pre-`ends_at` no-show → `ERR_INVALID_STATE` — live_sessions.py:111-112
- §3.6 Subscription create — insert — ambiguity — Client ownership of `client_id` checked before existence (`ERR_NOT_RESOURCE_OWNER` vs `ERR_REFERENCED_NOT_FOUND`) — subscriptions.py:33-36
- §3.6 Charge-cycle — insert — mismatch — returns `201` with the billing cycle; first-cycle `period_start`=clock, renewal=`cps`+7d (may precede clock) — subscriptions.py:79-81, 121
- §3.7 Pause — insert — ambiguity — `ERR_VALIDATION` also covers resume-not-after-clock and precedes the OCC version check; exactly 84d allowed — subscriptions.py:153-157
- §3.7 Pause credit expiry — revise — mismatch — expires every still-`AVAILABLE` credit from any cycle of the subscription (not only the literal current period) — subscriptions.py:172-175
- §3.8 Crisis ACUTE / resolve — insert — ambiguity — ACUTE always sets `risk_flag` but only suspends/freezes a currently-`ACTIVE` client; resolve clears flag/unfreezes always but restores to `ACTIVE` only if `SUSPENDED` — crisis.py:71-79, 116-120
- §3.9 Superbill — insert — mismatch — issue from non-`DRAFT` and zero-session issue → `ERR_INVALID_STATE`; `credits_granted` of 0 treated as 1 in the divisor; a counted session with no containing `PAID` cycle contributes 0 — superbills.py:42, 97-103

All pins were verified against the implementation; tests were treated only as auxiliary cross-reference. No new sections were added and no behavior was invented.
