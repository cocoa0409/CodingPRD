import { Request } from 'express';
import { Errors } from './errors';

export function validateVersionIfProvided(
  req: Request,
  currentVersion: number
): void {
  const providedVersion = req.body.version ?? req.headers['if-match'];

  if (providedVersion === undefined) {
    return;
  }

  const versionNumber = typeof providedVersion === 'string'
    ? parseInt(providedVersion, 10)
    : providedVersion;

  if (versionNumber !== currentVersion) {
    throw Errors.VERSION_MISMATCH();
  }
}
