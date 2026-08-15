# Worklog — task_1870_neighborhood_watch_community_safety

## Step 1: Create task directory — 2026-08-14T21:53:00.000Z

Pre-created by pipeline launcher: `tasks/task_1870_neighborhood_watch_community_safety/` and `tasks/task_1870_neighborhood_watch_community_safety/workspace/` (orchestrator verified existence; no index scan performed per instructions).

## Step 2: Generate scaffold — 2026-08-14T22:22:20.627Z

There's a pre-existing empty `workspace` directory (created by the task scaffolding, not by me) — I'll leave it untouched. All three required artifacts are in place.

## Report

Generated the complete scaffold for task 1870 (Neighborhood Watch & Community Safety Program) at `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/`:

- **SCAFFOLD.yaml** (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys): 12 entities, 71 endpoints, 20 error codes, 17-priority validation lattice, 5 calculations, 10 state machines, 2 OCC concurrency rules, 4 roles.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single `scaffold_difficulty_design` key): 18 instances, exactly 2 per each of the 9 difficulty rules.
- **SCAFFOLD_CORNER_DESIGN.yaml** (single `scaffold_corner_design` key): 46 corner instances (41 active + 5 `excluded_because` stubs) across all 9 claim-extraction-guide sections.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (639 calls scanned).

**Harder-than-expert design choices:**
- **Archetype blend:** compliance/audit + access-control matrix with segregation-of-duties role model (reporter can't review own incident; trainer can't certify own group; assigned-officer identity pinning on reviews).
- **Posture-driven gating:** derived WatchGroup posture (DORMANT/FORMATION/OPERATIONAL/DEGRADED/FROZEN) gates alert send, member writes, event proposals.
- **Rule highlights:** dual-variant calcs on two domains (participation census/activity on WatchGroup; risk-heat provisional/corroborated-only on Block); combinatorial formulas in modes (a) tiered certification points and (b) per-block-ceil-then-sum alert fanout (2-block phone-tree fixture diverges 6 vs 5); cyclic IncidentReport review loop + parallel Alert dimensions (distribution × ack posture); depth-4 suspend cascade (member → captain revocation → posture DEGRADED → alert gated) and depth-2 deregister cascade; temporal overlap with contrasting interval semantics (meeting rooms half-open adjacency-allowed vs event closures buffer-inclusive touching-forbidden); compensating invariants on active-captain-count and materials-inventory conserved quantities.
- **Two genuine scaffold gaps found and repaired during recipe replay** (per the §1.5 priority ladder): added `POST /watch/watch-groups/{id}/certification-suspend` + `certification-reinstate` (FROZEN was unreachable), and re-pointed the `ERR_NO_ACTIVE_CAPTAIN` check from alert queue (unreachable behind the posture gate) to alert creation.
- All formula-derived assertions were pre-computed with Python (e.g., certification points 45/80, risk heat 5.5/3.0/1.75, fanout 6, participation 30→43, quorum thresholds) and pinned as literals; every OCC `expected_*_version` references a prior `captures:` binding; the logical clock defaults to `2026-08-01T00:00:00Z`.

## Step 3: Copy shared files — 2026-08-14T22:22:40.202Z

Copied `./INSTRUCTION.md` → `tasks/task_1870_neighborhood_watch_community_safety/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T22:33:32.520Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/workspace/PRD.md`.

**Structure.** §1 introduction (2 paragraphs, problem/context angle); §2 with 12 subsections — RBAC with per-role identity prose (ProgramCoordinator opaque; LiaisonOfficer entity-backed; BlockCaptain/Member member-backed), verbatim §2.2 envelope block (byte-identical match confirmed), pagination, common resource properties, the logical clock (`2026-08-01T00:00:00Z` default, lazy agreement-expiry sweep), the fixed 17-rung validation-priority ladder with left-to-right 404 resolution, OCC, derived-posture reconciliation, precision disciplines, materials/depot conservation (50-sign budget), quiet hours (22:00–07:00, `INCIDENT_BULLETIN` exempt), and segregation/visibility scoping. §3 has 8 domain-derived subsections (founding/registration, membership/captaincy, incident review loop + heat decay, alerts/fan-out/ack, meetings + data-sharing, training cooldown, events/closures, certification + participation score) with all five calculations rendered as precise prose — including the pinned per-block-ceil fan-out order with the scaffold's 2×`PHONE_TREE` → 6-vs-5 divergence example, per-term half-up 2dp heat rounding, quorum snapshot ordering, and dual-variant participation/certification thresholds (60/40/80, 24/12-month grants). §4 is a 71-row 4-column endpoint table; §5 is the 20-row 2-column error catalogue.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + common + endpoint inputs: 80 required, 80 present, 0 missing
- endpoints[].query_params (second pass): 28 required, 28 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 17 rungs expressed as an explicit ordered ladder, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_watch_group_version / expected_block_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 34 checked, all from/to state pairs present with preconditions and side effects, 0 missing
- calculations[]: 5 checked (participation_score, block_risk_heat, certification_points, alert_fanout, meeting_quorum), all formulas/constants/precision/variants in prose, 0 missing
- validations[] conditions: 17 checked, each matchable to its error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: cascades (captain revocation, member withdrawal, visibility re-scope, heat recompute, flyer compensation, cooldown arming) expressed, 0 missing
- entities[].fields[] structured content: defaults, nullability, enum sets, strike limit 3, depot budget 50 reconstructible, 0 missing
- sibling-branch symmetry: freeze from 3 postures, dual cancel paths (event/agreement/training), dual withdrawal paths, review fork PENDING/CONDITIONAL × APPROVED/REJECTED all at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 422
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced. One judgment call worth flagging: the scaffold's alert-create posture gate (validation 5) doesn't enumerate the permitted set, but validation 11.5's note requires `ERR_NO_ACTIVE_CAPTAIN` to remain reachable at create; I resolved this as drafting permitted in `OPERATIONAL`/`DEGRADED`, rejected while `FROZEN` — the only reading consistent with the captain-check rationale.

## Step 6: Generate implementation — 2026-08-14T22:45:39.197Z

The implementation is complete. Here is a summary of what was generated:

## Implementation Summary

**Location**: `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/workspace/implementation/`

### Files Created

| File | Purpose |
|------|---------|
| `start.sh` | Launcher: guards `pip install` behind `import flask` check, `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask entry point, error handlers, blueprint registration, `0.0.0.0:$PORT` |
| `db.py` | In-memory stores (12 entity dicts), logical clock (defaults to `2026-08-01T00:00:00Z`), ISO-8601 helpers |
| `errors.py` | `ApiError` class + constructors for all 19 error IDs from the scaffold |
| `response.py` | Envelope helpers producing `{meta, response_type, data}` with pagination fields `limit/offset/total_count/has_more` |
| `middleware.py` | `X-User-ID`/`X-User-Role` extraction, role validation against the 4 declared roles |
| `services/core.py` | Posture recompute, participation score (CENSUS/ACTIVITY variants), block risk heat (Decimal per-term rounding), alert fanout (per-block ceil then sum), certification points, meeting quorum, quiet hours, cascade helpers, agreement expiry sweep |
| `routes/clock.py` | `POST /watch/_clock/set_current_utc` |
| `routes/watch_groups.py` | CRUD + certification-suspend/reinstate, freeze/unfreeze, materials issue/recall (depot budget=50) |
| `routes/blocks.py` | Create/list/get, register/deregister with case-insensitive street_segment uniqueness, member withdrawal cascade |
| `routes/members.py` | Enroll/list/get, suspend/reinstate/withdraw with posture gating and roster visibility scoping for LiaisonOfficer |
| `routes/captain_assignments.py` | Create with OCC on `expected_block_version`, supersede semantics, relieve, list endpoints |
| `routes/incident_reports.py` | File/list/get, begin-review/request-info/resubmit/corroborate/dismiss/clear with segregation of duties and data-share gating |
| `routes/alerts.py` | Create with OCC on `expected_watch_group_version`, queue/send/unqueue/recall/ack with quiet hours, posture gating, per-block ceil fanout, materials ledger conservation, ack posture parallel dimension |
| `routes/liaison_officers.py` | Register/list/get with badge_number uniqueness |
| `routes/liaison_meetings.py` | Schedule with half-open room-slot overlap check, mark-held with quorum, cancel |
| `routes/data_share_agreements.py` | Draft/activate/revoke with precinct match, lazy expiry sweep, re-scope cascade |
| `routes/training_sessions.py` | Schedule with cooldown check, complete with attendee stamping and 24h cooldown arming, cancel |
| `routes/community_events.py` | Propose with buffer-inclusive closure conflict (2h buffer, closed interval), approve with certification + data-share gates, complete, cancel |
| `routes/certification_reviews.py` | Open with segregation-of-duties and duplicate checks, decide with threshold-based APPROVED/REJECTED/CONDITIONAL branches |

### Key Design Decisions

- **69 routes** registered covering all endpoints from the scaffold
- **No seeding** — store starts empty on every boot
- **Logical clock** defaults to `2026-08-01T00:00:00Z`, never falls back to wall-clock
- **Decimal arithmetic** for block risk heat (per-term `ROUND_HALF_UP` to 2dp)
- **Per-block ceil** for alert fanout before cross-block summation
- **Lazy expiry** of DataShareAgreements checked on every read/write touching them
- **Posture** derived from first principles: DORMANT -> FORMATION -> OPERATIONAL/DEGRADED/FROZEN with all cascade paths
- **Segregation of duties** enforced on incident review/dismiss and certification review create/decide
- **OCC** on alert creation (`expected_watch_group_version`) and captain assignment (`expected_block_version`)

(Note: Step 6 ran concurrently with Step 5; Step 5's test-generation subagent is still running at this timestamp and will be logged on completion.)

## Step 5: Generate unit tests — 2026-08-14T23:03:13.381Z

All done. Final state verified: 75 tests collected cleanly, 103/103 docstring citations are verbatim PRD substrings, tag audit clean.

## Summary

**Generated Stage 1 — `test_helpers/`** (in `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/`):
- `types.py` — 21 status enums + 12 entity TypedDicts (all entities carry the common id/created_at/updated_at/version fields)
- `api_client.py` — 71 endpoint methods covering every PRD endpoint incl. the logical-clock control
- `api_errors.py` — 20 error ids with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — 12 entity assertions + `assert_group_invariants`
- `factories.py` — 20 payload factories (input fields only)
- `constants.py` — participation weights, heat buckets, certification thresholds/caps, fan-out relay/flyer ratio, quorum fraction, depot budget, quiet hours, permit tier, closure buffer, cooldown
- `test_users.py` — opaque `ProgramCoordinator` constant plus per-instance builders for entity-backed `LiaisonOfficer`/`BlockCaptain`/`Member`
- `fixtures.py` — composite workspaces: `setup_operational_group`, `setup_cert_scoring_group` (parameterized 45/80-point builds), `hold_quorum_meeting`, `send_group_alert`, `create_active_agreement`, OCC-threading `create_alert`/`assign_captain`

**Generated Stage 2 — `test_suite/`**: `conftest.py` + 12 test files, **75 tests**.

**Coverage audit (clean)**:
- All 18 difficulty instances: ≥2 tests each
- All 41 non-stub corner instances: 38 covered; all 5 stubs untranslated; zero tag mismatches
- **3 corner instances skipped** per the PRD-first filter (gaps left as gaps, no weakening/placeholders):
  - `member_computed_fields_input_ignored_on_create` — PRD never states unknown/computed body fields are ignored on create
  - `deregister_blocked_by_open_incident_reports` — PRD §3.1 describes the guard but names no error id
  - `mark_held_before_slot_start_rejected` — PRD §3.5 states the clock precondition but names no error id

**Judgment calls worth noting**:
- `event_closure_buffer_inclusive_zero_gap_rejected`: the yaml's probe times (14:00:00/14:00:01) contradict the PRD's both-sides-buffered rule (anchor 10:00–12:00 buffers to [08:00,14:00]; a 14:00-starting probe buffers to [12:00,…] and overlaps). I kept the instance's asserted rule (touch rejected, 1-second gap accepted) with corrected probe times (16:00:00 / 16:00:01) and documented the derivation in the docstring.
- `street_segment_uniqueness_among_live_blocks`: case-insensitivity is PRD-pinned only at registration time, so the create-time rejection uses a same-case duplicate; the case variant is used only on the post-deregistration success branch (safe under both readings).
- Initial-version literals (`version == 1`) are never PRD-stated, so tests assert relative increments (`v_post == v_pre + 1`) and dynamically captured versions instead of literals.
- Alert drafting in FORMATION rests on PRD §3.4's explicit phrasing that the posture gate "guards queueing and sending" and that only a FROZEN group rejects alert writes — this backs the OCC and no-active-captain corner setups.

## Step 7: Run tests and iterate — 2026-08-14T23:20:10.492Z

# Summary

**Task**: task_1870_neighborhood_watch_community_safety — all 75 tests now pass in all 8 parallel rounds (final sweep: 75/75 × 8, union of failures empty).

**Iterations run**: 5 sweeps total. Iteration 1 surfaced 6 deterministic failures (identical in all 8 rounds). Iterations 2–3 were destroyed mid-flight by external SIGKILLs from other pipelines sharing this host (runners "Killed"; no OOM in syslog; memory at 17/123 GB used). Iteration 4 completed with 5/8 rounds clean and 3 rounds carrying only `requests.exceptions.ConnectionError` (per-test server murdered mid-request by the same external interference — no assertion failures). Iteration 5, run under a resilient driver that relaunches rounds with missing results or infrastructure-only failures and halts on any real assertion failure, completed with a full clean sweep on its first attempt.

**Tests deleted**: none. Every failing test traced to verbatim PRD prose; no test weakened, no skip/xfail added.

**Fixes applied to `test_helpers/`**: none needed — fixtures, factories, and role-header builders were all PRD-consistent.

**Fixes applied to `test_suite/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/test_suite/test_07_cascades_and_posture.py` — renamed module-level helper `__formation_group_with_training` → `_formation_group_with_training` (call site at line 230 sits inside class `TestImmediateConsistency`, so Python name-mangled the double-underscore reference to `_TestImmediateConsistency__formation_group_with_training`, producing a `NameError`). Pure test-code bug; the test's PRD-faithful assertion (immediate posture visibility per §2.8) is unchanged.

**Fixes applied to `implementation/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/workspace/implementation/services/core.py` — `recompute_posture` + `_recompute_participation`: one triggering mutation now produces exactly one group `version` increment even when posture and participation score change together (previously `touch()` on posture change plus an unconditional score-change bump produced 1→3 on first-block registration, violating PRD §3.1's singular "the group's `version` increments" and §2.4's per-mutation increment).
- `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/workspace/implementation/routes/alerts.py` — `create_alert`: removed the extra gate restricting drafting to OPERATIONAL/DEGRADED. PRD §3.4 names only FROZEN as rejecting alert writes and pins the posture gate to "queueing and sending" so that `ERR_NO_ACTIVE_CAPTAIN` surfaces at creation "instead of being masked by the posture gate". This unblocked three tests (quiet-hours-at-create on a DORMANT group, no-active-captain on a FORMATION group, and the fresh-version 201 branch of the OCC test).
- `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/workspace/implementation/routes/community_events.py` — `approve_event`: reordered gates to closure-conflict (temporal) → data-share gate → certification gate, matching PRD §2.6's priority list ("then the data-sharing gate (`ERR_DATA_SHARE_REQUIRED`); then the certification gate (`ERR_CERTIFICATION_REQUIRED`)"). Previously certification was checked first, so a 100-attendee event with no ACTIVE agreement wrongly surfaced `ERR_CERTIFICATION_REQUIRED`.

**Infrastructure note for future runs on this host**: concurrent pipelines issue broad kills that SIGKILL `prd-bench-local-run` processes; a retry-driver wrapper (relaunch rounds with missing results or exclusively `ConnectionError`-class failures; abort on assertion failures) was required to land a clean 8-round sweep.

(Orchestrator verification: all 8 `results.{1..8}.json` files present, each reporting total=75, passed=75, failed=0.)

## Step 8: Finalize PRD — 2026-08-14T23:26:25.844Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1870_neighborhood_watch_community_safety/workspace/PRD_FINALIZED.md` written.

## Line counts / delta
- PRD.md: 310 lines, 54,257 chars — PRD_FINALIZED.md: 310 lines, 55,006 chars
- Delta: +0.00% lines, +1.38% chars (4 in-place edits, no new sections)

## Changes (one bullet per edit)
- **§2.8** — revise — split the reconciliation sentence to pin that one reconciliation increments the group's `version` exactly once even when posture and participation score change in the same pass (not once per changed derived field) — `implementation/services/core.py:97-120` (`recompute_posture`, `bump=False` + single `touch`)
- **§3.4** — revise — drafting now accepted in any posture other than `FROZEN` (was "accepted while `OPERATIONAL` or `DEGRADED`", a PRD/impl mismatch); posture gate guards queueing and sending only — `implementation/routes/alerts.py:87-91`
- **§3.7** — insert — explicit evaluation order at approval per §2.6: closure-conflict re-check → data-sharing gate → certification gate — `implementation/routes/community_events.py:155-171`
- **§4 table** (approve row) — revise — gate list reordered from "certification, closure, and attendance" to "closure, attendance, and certification" to mirror the pinned evaluation order — `implementation/routes/community_events.py:155-171`

No edit for the `test_07` helper rename (pure test-code NameError bug) — PRD is silent on test internals by design.

## Per-edit pre-edit search log

**Edit 1 (§2.8 version pin).** (a) Subject: group `version` increment when one mutation changes multiple derived fields. (b) Enumerated: `services/core.py` (`touch` L24-27, `recompute_posture` L97-120 incl. FROZEN early-return branch, `_recompute_participation` L169-199); every `recompute_posture` callsite — blocks.py:133/165, captain_assignments.py:93/168, members.py:88/162/189/222, training_sessions.py:167, incident_reports.py:221, liaison_meetings.py:157, community_events.py:197, certification_reviews.py:202/215/228, watch_groups.py:123/139/174; every direct `touch(g)` — watch_groups.py:122/138/157/176/198/221, training_sessions.py:164, certification_reviews.py:200/213/226, alerts.py:251/286. (c) Wording scoped to "exactly one **per reconciliation**" rather than "one per request/mutation", because compound handlers legitimately bump twice in one request (training complete: cooldown touch + recompute; certification decide: cert-status touch + recompute; freeze: posture touch + `_recompute_participation(bump=True)`; unfreeze: recompute + unconditional touch). Verified the scoped claim holds on every enumerated path.

**Edit 2 (§3.4 drafting gate).** (a) Subject: which postures permit alert drafting. (b) Enumerated all alert posture checks: alerts.py create:90 (FROZEN-only), queue:189 (exactly OPERATIONAL), send:229 (exactly OPERATIONAL), unqueue:256 / recall:271 / ack:294 (no posture gate); cross-checked parallel FROZEN-only write gates at members.py:67/179 and community_events.py:90; confirmed PRD's queue/send sentences (untouched) still match impl. (c) Added "the posture gate otherwise guarding queueing and sending rather than drafting" so the new sentence stays consistent with the untouched queue/send OPERATIONAL-exact wording and with the preceding `ERR_NO_ACTIVE_CAPTAIN` sentence.

**Edit 3 (§3.7 approval order).** (a) Subject: evaluation order of closure/data-share/certification checks at event approval. (b) Enumerated: community_events.py approve_event:142-175 (state → closure → data-share at ≥100 → certification; `has_active_agreement` core.py:79-90, any scope), create_event:58-106 (FROZEN → closure only; proposal path untouched by wording), complete_event:178-199, cancel_event:202-225; confirmed §2.6's priority list already orders data-share before certification. (c) Worded as "the closure-conflict re-check first, then the data-sharing gate, then the certification gate" without adding any posture-gate claim for approval (impl has none on approve) and without touching the proposal-time FROZEN/closure sentences.

**Edit 4 (§4 table row).** (a) Subject: same as Edit 3 (the description cell's noun order was a second, misleading signal of certification-first). (b) Same enumeration as Edit 3. (c) Pure noun reorder in a non-normative description cell; verified it matches approve_event's actual check sequence exactly.

## Step 9: Complete PRD — 2026-08-14T23:45:15.156Z

Done. PRD_COMPLETED.md is written and verified against the implementation.

## Summary

**Source vs output**: `workspace/PRD_FINALIZED.md` (310 lines / 55,205 chars) → `workspace/PRD_COMPLETED.md` (315 lines / 65,367 chars), +5 lines / +10,162 chars, 36 edit sites, all inline inserts or in-paragraph revisions; no new sections, no restructured tables (one row appended to §5).

**Counts**: 26 ambiguity-pins, 10 mismatch-revisions.

### Changes (section — insert|revise — class — what — impl ref)

- §2.1 — revise — mismatch — dropped the false claim that an acknowledgement's `member_id` is compared to `X-User-ID`; pinned that member-ownership checks exist only at resubmission and self-withdrawal, and that report filing does not bind `reporter_member_id` to the caller — routes/alerts.py:294-322, routes/incident_reports.py:36-89
- §2.2 — insert — ambiguity — undefined path/unsupported method → `ERR_NOT_FOUND` 404; server failure → `ERR_INTERNAL` 500 — app.py:20-32
- §2.3 — insert — ambiguity — unparseable/out-of-range `limit`/`offset` fall back/clamp (no error); `total_count` = filtered count pre-pagination; `has_more` ⇔ offset+limit < total_count — routes/watch_groups.py:225-236, response.py:17
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — services/core.py:30-35
- §2.5 — insert — ambiguity — clock setter has no monotonicity check; missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — routes/clock.py:12-24
- §2.6 — revise — mismatch — rewrote the validation priority to impl's actual order: creation-body field validation up front (4th), body-reference existence at first dereference (5th), `ERR_STALE_VERSION` (6th), actor-ownership 403s (9th), temporal rules after referential/captain-coverage and "where the endpoint examines the times", action-body validation per §3; flagged reinstate/withdraw exceptions — all routes
- §2.7 — insert — ambiguity — OCC check fires right after the guarded parent resolves; missing expected-version field → `ERR_INVALID_REQUEST` — routes/alerts.py:63-64,81-85; routes/captain_assignments.py:44-53
- §2.8 — insert — ambiguity — FROZEN suspends posture derivation; the FROZEN gate covers exactly enrollment, reinstatement, alert drafting, event proposal (everything else enumerated as available); REVOKED standing freezes posture derivation in place — services/core.py:97-120,123-162
- §2.10 — insert — ambiguity — `signs`/`materials` default 0, non-integer/negative → `ERR_INVALID_REQUEST` before conservation checks; recall validates both ledgers before applying either subtraction — routes/watch_groups.py:180-222
- §2.11 — insert — ambiguity — quiet hours evaluated on the logical clock's UTC reading, 22:00:00 inclusive to 07:00:00 exclusive — services/core.py:401-404
- §2.12 — revise — mismatch — revoked/expired agreements leave `shared_with_liaison` true, so previously shared reports remain liaison-readable via the flag (PRD had claimed reads are denied); also pinned single-member liaison fetch → `ERR_NOT_FOUND` and no scoping on the incident list — services/core.py:55-62, routes/incident_reports.py:92-138, routes/members.py:128-142
- §3.1 — insert — ambiguity — group-name uniqueness is exact, case-sensitive — routes/watch_groups.py:54-56
- §3.1 — revise — ambiguity — `street_segment` uniqueness at block creation is case-insensitive among non-deregistered blocks — routes/blocks.py:49-54
- §3.1 — insert — ambiguity — registering under a REVOKED group → `ERR_INVALID_STATE` — routes/blocks.py:113-115
- §3.1 — insert — ambiguity — both deregistration guards are `ERR_INVALID_STATE`, open-incident guard first — routes/blocks.py:148-156
- §3.2 — revise — mismatch — FROZEN gates only enrollment and reinstatement (PRD had said "every member write"); suspension and withdrawal remain available while frozen; enrollment does not require a REGISTERED block — routes/members.py:66-68,145-224
- §3.2 — revise — mismatch — strike-limit-3 auto-suspension is inert: no operation records strikes; all suspensions are coordinator-initiated — routes/members.py (STRIKE_LIMIT never used)
- §3.2 — insert — ambiguity — reinstatement evaluates the FROZEN gate before the state check; withdraw self-check is `ERR_UNAUTHORIZED` evaluated before state checks; member withdrawing a SUSPENDED record → `ERR_UNAUTHORIZED` — routes/members.py:167-224
- §3.2 — insert — ambiguity — captain appointment is not posture-gated and does not require a REGISTERED block; relieve likewise ungated — routes/captain_assignments.py:31-95,151-170
- §3.3 — revise — ambiguity — `last_incident_at` recomputed from reports contributing under the active heat variant (post-revocation it ignores cleared reports, may return to null) — services/core.py:212-257
- §3.4 — insert — ambiguity — alert-creation check order pinned (fields → group existence → version → FROZEN gate → target block/captain → origin incident → quiet hours last); no clock constraint on `scheduled_send_at` at drafting — routes/alerts.py:52-115
- §3.4 — revise — mismatch — removed the "system itself sends at scheduled_send_at" auto-dispatch claim (no such mechanism exists); sending is always the explicit coordinator action; pinned queue re-verification (block REGISTERED + captain) and send order (state → posture → scheduled-instant → quiet hours) — routes/alerts.py:175-253, routes/clock.py
- §3.4 — revise — mismatch — recall credits the flyer quantity clamped at zero, not unconditionally "exactly" — routes/alerts.py:285
- §3.4 — insert — ambiguity — acknowledgement has no `distribution_status` gate, accepts any existing member id (no audience/ACTIVE/actor binding); missing → `ERR_INVALID_REQUEST`, unknown → `ERR_NOT_FOUND` — routes/alerts.py:294-322
- §3.5 — insert — ambiguity — meeting scheduling not bound to the named chair; no clock constraint on slots; birth carries `quorum_met` false / `attendee_count` null — routes/liaison_meetings.py:33-88
- §3.5 — insert — ambiguity — mark-held error ids and order: wrong chair `ERR_UNAUTHORIZED`, early clock `ERR_INVALID_STATE`, bad `attendee_count` `ERR_INVALID_REQUEST` — routes/liaison_meetings.py:123-159
- §3.5 — revise — mismatch — meeting cancellation open to any liaison officer, not only the chair — routes/liaison_meetings.py:162-174
- §3.5 — revise — mismatch — revocation cascade keeps report flags (reads via flag persist); also pinned: unlimited coexisting agreements (multiple ACTIVE allowed), activation errors (`ERR_UNAUTHORIZED`/`ERR_INVALID_STATE` after precinct re-check), revocation not ownership-bound — routes/data_share_agreements.py:114-148, services/core.py:55-72
- §3.6 — insert — ambiguity — scheduling not bound to the named trainer; no clock constraint on `scheduled_at`; birth carries `attending_member_ids` null — routes/training_sessions.py:35-79
- §3.6 — insert — ambiguity — completion: wrong officer `ERR_UNAUTHORIZED`, bad attendee entries `ERR_INVALID_REQUEST`, no clock gate; session cancel open to any officer/coordinator — routes/training_sessions.py:117-184
- §3.7 — insert — ambiguity — `estimated_attendance` defaults to 0 — routes/community_events.py:67
- §3.7 — insert — ambiguity — event-cancel role/state error ids: cross-role attempts `ERR_UNAUTHORIZED`; late/terminal cancels `ERR_INVALID_STATE` — routes/community_events.py:202-225
- §3.8 — insert — ambiguity — captaincy term is zero when the group has no REGISTERED blocks (no vacuous-truth 15) — services/core.py:380-388
- §3.8 — insert — ambiguity — decide pins: wrong officer `ERR_UNAUTHORIZED`; invalid `decision` `ERR_INVALID_REQUEST` (after state check, before officer check); threshold shortfalls and CONDITIONAL-on-CONDITIONAL `ERR_INVALID_STATE`; recomputed points persisted on the review even on rejected decisions; month addition is calendar-month with day clamping — routes/certification_reviews.py:128-234
- §3.8 — revise — mismatch — REVOKED-on-rejection keyed to the group being CERTIFIED at decision time (PRD had "previously CERTIFIED … renewal"); unfreeze lands on the freshly derived posture, not unconditionally OPERATIONAL; suspension clears `certification_valid_until`, reinstatement leaves it null — routes/certification_reviews.py:162-215, routes/watch_groups.py:112-177
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row — app.py:30-32

Notable findings for the caller: the two largest semantic mismatches fixed were (1) the PRD's post-revocation "liaison reads are denied" claim — the implementation retains `shared_with_liaison=true`, so corroborated/cleared reports remain officer-readable after revocation; and (2) the PRD's automatic alert dispatch at `scheduled_send_at` — no auto-send exists. The §2.6 global validation order also needed a substantive rewrite: the implementation validates creation bodies up front and checks alert quiet-hours last at creation, contrary to the original list.
