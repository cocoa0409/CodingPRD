import db from '../db/schema';
import { v4 as uuidv4 } from 'uuid';
import {
  Studio, StudioRow, StudioPosture, Effect, MixRow, MixStatus,
  DisputeRow, AssetRow, ClearanceRow
} from '../types';

export function calculatePosture(studioId: string): StudioPosture {
  const disputes = db.prepare(`
    SELECT * FROM disputes WHERE studio_id = ? AND status IN ('OPEN', 'ESCALATED')
  `).all(studioId) as DisputeRow[];

  const hasEscalated = disputes.some(d => d.status === 'ESCALATED');
  if (hasEscalated) return 'HALT';

  const openCount = disputes.filter(d => d.status === 'OPEN').length;
  if (openCount >= 2) return 'REVIEW';

  return 'OPEN';
}

export function calculateTokenReserved(studioId: string): number {
  const result = db.prepare(`
    SELECT COALESCE(SUM(token_cost), 0) as total FROM mixes
    WHERE studio_id = ? AND status IN ('SUBMITTED', 'APPROVED') AND kind != 'EVIDENCE'
  `).get(studioId) as { total: number };
  return result.total;
}

export function calculateTokenCommitted(studioId: string): number {
  const result = db.prepare(`
    SELECT COALESCE(SUM(token_cost), 0) as total FROM mixes
    WHERE studio_id = ? AND status IN ('PUBLISHED', 'FROZEN') AND kind != 'EVIDENCE'
  `).get(studioId) as { total: number };
  return result.total;
}

export function getStudioWithDerived(studioId: string): Studio | null {
  const row = db.prepare('SELECT * FROM studios WHERE id = ?').get(studioId) as StudioRow | undefined;
  if (!row) return null;

  const posture = calculatePosture(studioId);
  const token_reserved = calculateTokenReserved(studioId);
  const token_committed = calculateTokenCommitted(studioId);
  const token_available = row.token_budget - token_reserved - token_committed;

  return {
    id: row.id,
    name: row.name,
    cycle_index: row.cycle_index,
    token_budget: row.token_budget,
    token_reserved,
    token_committed,
    token_available,
    posture,
    version: row.version,
  };
}

export function createStudio(name: string, tokenBudget: number = 100): Studio {
  const id = uuidv4();
  db.prepare(`
    INSERT INTO studios (id, name, token_budget, cycle_index, version)
    VALUES (?, ?, ?, 1, 1)
  `).run(id, name, tokenBudget);

  return getStudioWithDerived(id)!;
}

export function advanceCycle(studioId: string): { studio: Studio; effects: Effect[] } {
  const effects: Effect[] = [];
  const studioRow = db.prepare('SELECT * FROM studios WHERE id = ?').get(studioId) as StudioRow;
  const oldCycleIndex = studioRow.cycle_index;

  
  db.prepare('DELETE FROM idempotency_keys WHERE studio_id = ? AND cycle_index = ?').run(studioId, oldCycleIndex);

  
  const queuedMixes = db.prepare(`
    SELECT * FROM mixes WHERE studio_id = ? AND status IN ('SUBMITTED', 'APPROVED')
  `).all(studioId) as MixRow[];

  for (const mix of queuedMixes) {
    db.prepare(`
      UPDATE mixes SET status = 'DRAFT', approved_in_cycle = NULL, version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(mix.id);
    effects.push({
      type: 'mix',
      id: mix.id,
      status: 'DRAFT',
      version: mix.version + 1,
      token_cost: mix.token_cost,
    });
  }

  
  const liveMixes = db.prepare(`
    SELECT * FROM mixes WHERE studio_id = ? AND status IN ('PUBLISHED', 'FROZEN')
  `).all(studioId) as MixRow[];

  for (const mix of liveMixes) {
    db.prepare(`
      UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(mix.id);
    effects.push({
      type: 'mix',
      id: mix.id,
      status: 'ARCHIVED',
      version: mix.version + 1,
      token_cost: mix.token_cost,
    });
  }

  
  db.prepare(`
    UPDATE studios SET cycle_index = cycle_index + 1, version = version + 1
    WHERE id = ?
  `).run(studioId);

  const studio = getStudioWithDerived(studioId)!;
  effects.unshift({
    type: 'studio',
    id: studioId,
    version: studio.version,
    token_reserved: studio.token_reserved,
    token_committed: studio.token_committed,
    token_available: studio.token_available,
    posture: studio.posture,
    cycle_index: studio.cycle_index,
  });

  return { studio, effects };
}

export function shedBudget(studioId: string): Effect[] {
  const effects: Effect[] = [];
  const studio = getStudioWithDerived(studioId)!;

  while (studio.token_reserved + studio.token_committed > studio.token_budget) {
    
    const queuedMix = db.prepare(`
      SELECT * FROM mixes
      WHERE studio_id = ? AND status IN ('SUBMITTED', 'APPROVED') AND kind != 'EVIDENCE'
      ORDER BY
        CASE kind WHEN 'INTERNAL' THEN 0 ELSE 1 END,
        token_cost DESC,
        id ASC
      LIMIT 1
    `).get(studioId) as MixRow | undefined;

    if (queuedMix) {
      db.prepare(`
        UPDATE mixes SET status = 'DRAFT', approved_in_cycle = NULL, version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(queuedMix.id);
      effects.push({
        type: 'mix',
        id: queuedMix.id,
        status: 'DRAFT',
        version: queuedMix.version + 1,
        token_cost: queuedMix.token_cost,
      });
      
      const newReserved = calculateTokenReserved(studioId);
      const newCommitted = calculateTokenCommitted(studioId);
      studio.token_reserved = newReserved;
      studio.token_committed = newCommitted;
      continue;
    }

    
    const liveMix = db.prepare(`
      SELECT * FROM mixes
      WHERE studio_id = ? AND status IN ('PUBLISHED', 'FROZEN') AND kind != 'EVIDENCE'
      ORDER BY
        CASE kind WHEN 'INTERNAL' THEN 0 ELSE 1 END,
        token_cost DESC,
        id ASC
      LIMIT 1
    `).get(studioId) as MixRow | undefined;

    if (liveMix) {
      db.prepare(`
        UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(liveMix.id);
      effects.push({
        type: 'mix',
        id: liveMix.id,
        status: 'ARCHIVED',
        version: liveMix.version + 1,
        token_cost: liveMix.token_cost,
      });
      const newCommitted = calculateTokenCommitted(studioId);
      studio.token_committed = newCommitted;
      continue;
    }

    
    break;
  }

  return effects;
}

export function getStudioEffect(studioId: string): Effect {
  const studio = getStudioWithDerived(studioId)!;
  return {
    type: 'studio',
    id: studioId,
    version: studio.version,
    token_reserved: studio.token_reserved,
    token_committed: studio.token_committed,
    token_available: studio.token_available,
    posture: studio.posture,
    cycle_index: studio.cycle_index,
  };
}
