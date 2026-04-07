export const ACTOR_TYPES = ['Customer', 'Support', 'Ops', 'System'] as const;
export type ActorType = typeof ACTOR_TYPES[number];

export const PROGRAM_POSTURES = ['PROGRAM_ACTIVE', 'PROGRAM_GUARDED', 'PROGRAM_FROZEN', 'PROGRAM_CLOSED'] as const;
export type ProgramPosture = typeof PROGRAM_POSTURES[number];

export const SESSION_STATUSES = ['ACTIVE', 'ENDED', 'REVOKED'] as const;
export type SessionStatus = typeof SESSION_STATUSES[number];

export const DEFAULT_ACTOR_TYPE: ActorType = 'System';
