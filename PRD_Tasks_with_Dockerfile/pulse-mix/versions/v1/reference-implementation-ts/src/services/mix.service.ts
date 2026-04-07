import db from '../db/schema';
import { v4 as uuidv4 } from 'uuid';
import {
  Mix, MixRow, MixKind, MixStatus, MixEntry, MixEntryRow,
  Effect, AssetRow, ClearanceRow, DisputeRow, SlotType
} from '../types';
import { getStudioWithDerived, calculateTokenReserved, calculateTokenCommitted, getStudioEffect } from './studio.service';
import { hasOpenDispute } from './asset.service';

export function getBaseCost(durationSec: number): number {
  if (durationSec <= 120) return 1;
  if (durationSec <= 240) return 2;
  if (durationSec <= 420) return 3;
  return 4;
}

export function calculateMixTokenCost(mixId: string): number {
  const mix = db.prepare('SELECT * FROM mixes WHERE id = ?').get(mixId) as MixRow | undefined;
  if (!mix) return 0;

  const entries = db.prepare(`
    SELECT me.*, a.duration_sec FROM mix_entries me
    JOIN assets a ON me.asset_id = a.id
    WHERE me.mix_id = ?
    ORDER BY me.position
  `).all(mixId) as (MixEntryRow & { duration_sec: number })[];

  if (entries.length === 0) return 0;

  let sum = 0;
  for (const entry of entries) {
    const baseCost = getBaseCost(entry.duration_sec);
    const slotAdjustment = entry.slot === 'SPOTLIGHT' ? 1 : 0;
    sum += baseCost + slotAdjustment;
  }

  if (mix.kind === 'EVIDENCE') return 0;
  if (mix.kind === 'INTERNAL') {
    const halfed = Math.floor(sum / 2);
    return halfed === 0 && entries.length > 0 ? 1 : halfed;
  }
  return sum;
}

export function getMix(mixId: string): Mix | null {
  const row = db.prepare('SELECT * FROM mixes WHERE id = ?').get(mixId) as MixRow | undefined;
  if (!row) return null;

  const entries = db.prepare(`
    SELECT asset_id, slot FROM mix_entries WHERE mix_id = ? ORDER BY position
  `).all(mixId) as MixEntry[];

  return {
    id: row.id,
    studio_id: row.studio_id,
    title: row.title,
    kind: row.kind,
    status: row.status,
    entries,
    token_cost: row.token_cost,
    approved_in_cycle: row.approved_in_cycle,
    published_in_cycle: row.published_in_cycle,
    version: row.version,
  };
}

export function createMix(studioId: string, title: string, kind: MixKind): Mix {
  const id = uuidv4();
  db.prepare(`
    INSERT INTO mixes (id, studio_id, title, kind, status, token_cost, version)
    VALUES (?, ?, ?, ?, 'DRAFT', 0, 1)
  `).run(id, studioId, title, kind);

  return getMix(id)!;
}

export interface EntryValidationResult {
  valid: boolean;
  error?: string;
}

export function validateEntries(
  studioId: string,
  kind: MixKind,
  entries: MixEntry[],
  isSubmit: boolean = false
): EntryValidationResult {
  const studio = getStudioWithDerived(studioId);
  if (!studio) return { valid: false, error: 'NOT_FOUND' };

  
  if (kind === 'EVIDENCE') {
    if (entries.length < 1 || entries.length > 10) {
      return { valid: false, error: 'ENTRY_LIMIT' };
    }
  } else {
    if (entries.length < 1 || entries.length > 25) {
      return { valid: false, error: 'ENTRY_LIMIT' };
    }
  }

  
  if (kind === 'PUBLIC') {
    const assetIds = new Set<string>();
    for (const entry of entries) {
      if (assetIds.has(entry.asset_id)) {
        return { valid: false, error: 'ENTRY_DUPLICATE_PUBLIC' };
      }
      assetIds.add(entry.asset_id);
    }
  }

  
  if (kind === 'INTERNAL' || kind === 'EVIDENCE') {
    for (let i = 1; i < entries.length; i++) {
      if (entries[i].asset_id === entries[i - 1].asset_id) {
        return { valid: false, error: 'ENTRY_ADJACENT_DUPLICATE' };
      }
    }
  }

  
  const spotlightCount = entries.filter(e => e.slot === 'SPOTLIGHT').length;

  if (kind === 'EVIDENCE' && spotlightCount > 0) {
    return { valid: false, error: 'SPOTLIGHT_NOT_ALLOWED' };
  }

  
  let spotlightCap: number;
  if (studio.posture === 'REVIEW' && kind !== 'EVIDENCE') {
    spotlightCap = 1;
  } else if (kind === 'PUBLIC') {
    spotlightCap = 3;
  } else if (kind === 'INTERNAL') {
    spotlightCap = 5;
  } else {
    spotlightCap = 0;
  }

  if (spotlightCount > spotlightCap) {
    return { valid: false, error: 'SPOTLIGHT_CAP_EXCEEDED' };
  }

  
  if (isSubmit) {
    for (const entry of entries) {
      const validation = validateAssetForMix(studioId, entry.asset_id, kind, entry.slot);
      if (!validation.valid) {
        return validation;
      }
    }
  }

  return { valid: true };
}

export function validateAssetForMix(
  studioId: string,
  assetId: string,
  kind: MixKind,
  slot: SlotType
): EntryValidationResult {
  const asset = db.prepare('SELECT * FROM assets WHERE id = ? AND studio_id = ?').get(assetId, studioId) as AssetRow | undefined;
  if (!asset) return { valid: false, error: 'NOT_FOUND' };

  
  const hasDispute = hasOpenDispute('ASSET', assetId);

  if (kind === 'EVIDENCE') {
    
    if (asset.status !== 'QUARANTINED') {
      if (hasDispute) {
        return { valid: false, error: 'DISPUTE_BLOCKING' };
      }
      return { valid: false, error: 'ASSET_QUARANTINED' }; 
    }
    if (!hasDispute) {
      return { valid: false, error: 'DISPUTE_BLOCKING' }; 
    }
    return { valid: true };
  }

  
  if (hasDispute) {
    return { valid: false, error: 'DISPUTE_BLOCKING' };
  }

  if (asset.status === 'QUARANTINED') {
    return { valid: false, error: 'ASSET_QUARANTINED' };
  }

  if (asset.status !== 'ACTIVE') {
    return { valid: false, error: 'ASSET_NOT_ACTIVE' };
  }

  
  const clearance = db.prepare('SELECT * FROM clearances WHERE asset_id = ?').get(assetId) as ClearanceRow | undefined;
  if (!clearance || clearance.status !== 'GRANTED') {
    if (clearance?.status === 'SUSPENDED') {
      return { valid: false, error: 'CLEARANCE_SUSPENDED' };
    }
    return { valid: false, error: 'CLEARANCE_REQUIRED' };
  }

  
  if (clearance.policy === 'PROMO') {
    if (kind === 'PUBLIC') {
      return { valid: false, error: 'CLEARANCE_POLICY_MISMATCH' };
    }
    if (slot === 'SPOTLIGHT') {
      return { valid: false, error: 'SPOTLIGHT_NOT_ALLOWED' };
    }
  }

  return { valid: true };
}

export function updateMixEntries(mixId: string, entries: MixEntry[]): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  if (mix.status === 'PUBLISHED' || mix.status === 'FROZEN' || mix.status === 'ARCHIVED') {
    return { error: 'INVALID_STATE' };
  }

  const validation = validateEntries(mix.studio_id, mix.kind, entries, false);
  if (!validation.valid) {
    return { error: validation.error! };
  }

  const effects: Effect[] = [];
  const wasQueued = mix.status === 'SUBMITTED' || mix.status === 'APPROVED';

  
  db.prepare('DELETE FROM mix_entries WHERE mix_id = ?').run(mixId);

  
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    db.prepare(`
      INSERT INTO mix_entries (id, mix_id, asset_id, slot, position)
      VALUES (?, ?, ?, ?, ?)
    `).run(uuidv4(), mixId, entry.asset_id, entry.slot, i);
  }

  
  const newTokenCost = calculateMixTokenCost(mixId);

  
  if (wasQueued) {
    db.prepare(`
      UPDATE mixes SET status = 'DRAFT', approved_in_cycle = NULL, token_cost = ?, version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(newTokenCost, mixId);
    effects.push(getStudioEffect(mix.studio_id));
  } else {
    db.prepare(`
      UPDATE mixes SET token_cost = ?, version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(newTokenCost, mixId);
  }

  const updated = getMix(mixId)!;
  return { mix: updated, effects };
}

export function submitMix(mixId: string): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  if (mix.status !== 'DRAFT') {
    return { error: 'INVALID_STATE' };
  }

  const studio = getStudioWithDerived(mix.studio_id);
  if (!studio) return { error: 'NOT_FOUND' };

  if (studio.posture === 'HALT') {
    return { error: 'POSTURE_BLOCKED' };
  }

  
  if (mix.kind === 'EVIDENCE') {
    return { error: 'INVALID_STATE' };
  }

  
  const validation = validateEntries(mix.studio_id, mix.kind, mix.entries, true);
  if (!validation.valid) {
    return { error: validation.error! };
  }

  
  const newReserved = studio.token_reserved + mix.token_cost;
  if (newReserved + studio.token_committed > studio.token_budget) {
    return { error: 'TOKEN_BUDGET_EXCEEDED' };
  }

  db.prepare(`
    UPDATE mixes SET status = 'SUBMITTED', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(mixId);

  const effects: Effect[] = [getStudioEffect(mix.studio_id)];
  const updated = getMix(mixId)!;
  return { mix: updated, effects };
}

export function approveMix(mixId: string): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  if (mix.status !== 'SUBMITTED') {
    return { error: 'INVALID_STATE' };
  }

  const studio = getStudioWithDerived(mix.studio_id);
  if (!studio) return { error: 'NOT_FOUND' };

  if (studio.posture === 'HALT') {
    return { error: 'POSTURE_BLOCKED' };
  }

  db.prepare(`
    UPDATE mixes SET status = 'APPROVED', approved_in_cycle = ?, version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(studio.cycle_index, mixId);

  const updated = getMix(mixId)!;
  return { mix: updated, effects: [] };
}

export function publishMix(mixId: string, role: 'manager' | 'legal'): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  const studio = getStudioWithDerived(mix.studio_id);
  if (!studio) return { error: 'NOT_FOUND' };

  const effects: Effect[] = [];

  if (mix.kind === 'EVIDENCE') {
    
    if (role !== 'legal') {
      return { error: 'ROLE_FORBIDDEN' };
    }
    if (mix.status !== 'DRAFT') {
      return { error: 'INVALID_STATE' };
    }

    
    const validation = validateEntries(mix.studio_id, mix.kind, mix.entries, true);
    if (!validation.valid) {
      return { error: validation.error! };
    }

    db.prepare(`
      UPDATE mixes SET status = 'FROZEN', published_in_cycle = ?, version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(studio.cycle_index, mixId);
  } else {
    
    if (role !== 'manager') {
      return { error: 'ROLE_FORBIDDEN' };
    }

    if (mix.status !== 'APPROVED') {
      return { error: 'INVALID_STATE' };
    }

    
    if (mix.approved_in_cycle !== studio.cycle_index) {
      return { error: 'CYCLE_STALE' };
    }

    
    if (mix.kind === 'PUBLIC' && studio.posture !== 'OPEN') {
      return { error: 'POSTURE_BLOCKED' };
    }
    if (mix.kind === 'INTERNAL' && studio.posture === 'HALT') {
      return { error: 'POSTURE_BLOCKED' };
    }

    db.prepare(`
      UPDATE mixes SET status = 'PUBLISHED', published_in_cycle = ?, version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(studio.cycle_index, mixId);

    effects.push(getStudioEffect(mix.studio_id));
  }

  const updated = getMix(mixId)!;
  return { mix: updated, effects };
}

export function unpublishMix(mixId: string, role: 'manager' | 'legal'): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  if (mix.status !== 'PUBLISHED' && mix.status !== 'FROZEN') {
    return { error: 'INVALID_STATE' };
  }

  
  if (role === 'legal' && mix.status !== 'FROZEN') {
    return { error: 'ROLE_FORBIDDEN' };
  }

  const studio = getStudioWithDerived(mix.studio_id);
  if (!studio) return { error: 'NOT_FOUND' };

  
  let newStatus: MixStatus;
  if (mix.approved_in_cycle === studio.cycle_index) {
    newStatus = 'APPROVED';
  } else {
    newStatus = 'DRAFT';
  }

  db.prepare(`
    UPDATE mixes SET status = ?, published_in_cycle = NULL, version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(newStatus, mixId);

  const effects: Effect[] = [getStudioEffect(mix.studio_id)];
  const updated = getMix(mixId)!;
  return { mix: updated, effects };
}

export function freezeMix(mixId: string): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  if (mix.status !== 'PUBLISHED') {
    return { error: 'INVALID_STATE' };
  }

  db.prepare(`
    UPDATE mixes SET status = 'FROZEN', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(mixId);

  const updated = getMix(mixId)!;
  return { mix: updated, effects: [] };
}

export function archiveMix(mixId: string): { mix: Mix; effects: Effect[] } | { error: string } {
  const mix = getMix(mixId);
  if (!mix) return { error: 'NOT_FOUND' };

  if (mix.status === 'ARCHIVED') {
    return { error: 'INVALID_STATE' };
  }

  db.prepare(`
    UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(mixId);

  const effects: Effect[] = [];
  const wasLiveOrQueued = ['SUBMITTED', 'APPROVED', 'PUBLISHED', 'FROZEN'].includes(mix.status);
  if (wasLiveOrQueued && mix.kind !== 'EVIDENCE') {
    effects.push(getStudioEffect(mix.studio_id));
  }

  const updated = getMix(mixId)!;
  return { mix: updated, effects };
}
